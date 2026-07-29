#!/usr/bin/env python3
"""负责自定义数据插件的扫描、环境管理、导入、删除与状态维护。"""

import hashlib
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import support as _support
from .runtime import CustomDataWorker
from .support import (
    CUSTOM_DATA_MANIFEST_NAME,
    CUSTOM_DATA_PLACEHOLDER,
    CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME,
    CustomDataDefinition,
    CustomDataDuplicateError,
    CustomDataError,
    CustomDataState,
    get_custom_data_directory,
    get_environment_root,
    get_runtime_python,
)

_environment_python = _support._environment_python
_load_definition = _support._load_definition
_locate_manifest_root = _support._locate_manifest_root
_rmtree_with_retry = _support._rmtree_with_retry
_safe_extract_zip = _support._safe_extract_zip
_validate_uniqueness = _support._validate_uniqueness


class CustomDataManager:
    """协调插件扫描、导入、独立环境、子进程执行和结果读取。"""

    def __init__(self, custom_directory=None, environment_root=None):
        """初始化插件目录、虚拟环境根目录、状态表、环境准备线程和线程锁。"""
        self.custom_directory = Path(custom_directory) if custom_directory else get_custom_data_directory()
        self.custom_directory.mkdir(parents=True, exist_ok=True)
        self.environment_root = Path(environment_root) if environment_root else get_environment_root()
        self.environment_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.states = {}
        self.workers = {}
        self.load_errors = {}
        self.last_scan_time = 0.0
        self._environment_threads = {}
        self._plugin_configs = {}
        self._runtime_enabled_names = set()
        self._runtime_initialized = False
        self.reload_scripts()

    def close(self):
        """停止全部插件常驻进程并释放通信管道。"""
        with self.lock:
            workers, self.workers = tuple(self.workers.values()), {}
        for worker in workers:
            worker.stop()

    def update_plugin_configs(self, configs):
        """更新 collect 调用使用的插件配置副本。"""
        with self.lock:
            self._plugin_configs = {
                str(name): dict(values)
                for name, values in (configs or {}).items()
                if isinstance(values, dict)
            }

    def update_plugin_enabled(self, enabled):
        """按 Monitor 持久配置同步全部插件启用状态。"""
        enabled = enabled if isinstance(enabled, dict) else {}
        with self.lock:
            names = set()
            workers_to_stop = []
            for name, state in self.states.items():
                desired = bool(enabled.get(name, True))
                state.runtime_enabled = desired
                if desired:
                    names.add(name)
                else:
                    worker = self.workers.get(name)
                    if worker is not None:
                        workers_to_stop.append(worker)
            self._runtime_enabled_names = names
        for worker in workers_to_stop:
            worker.stop()
        self.prepare_environments_async()

    def __del__(self):
        """在管理器回收时尽力清理仍在运行的插件进程。"""
        try:
            self.close()
        except Exception:
            pass

    def _plugin_candidates(self):
        """返回目录中包含 plugin.json 的插件目录候选项。"""
        return sorted(
            path for path in self.custom_directory.iterdir()
            if path.is_dir()
            and path.name != CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME
            and (path / CUSTOM_DATA_MANIFEST_NAME).is_file()
        )

    def reload_scripts(self):
        """重新扫描所有插件并校验数据 key 与任务名唯一性。"""
        with self.lock:
            definitions = {}
            keys = set()
            errors = {}
            for plugin_path in self._plugin_candidates():
                try:
                    definition = _load_definition(plugin_path, self.environment_root)
                    _validate_uniqueness(definition, keys, definitions)
                    definitions[definition.name] = definition
                    keys.add(definition.key)
                except Exception as error:
                    errors[str(plugin_path)] = traceback.format_exception_only(type(error), error)[-1].strip()
            old_states = self.states
            old_workers = self.workers
            old_enabled_names = set(self._runtime_enabled_names)
            initial_scan = not self._runtime_initialized
            self.states = {}
            self.workers = {}
            enabled_names = set()
            for name, definition in definitions.items():
                old_state = old_states.get(name)
                runtime_enabled = initial_scan or name in old_enabled_names
                if old_state and old_state.definition.path == definition.path:
                    definition_changed = old_state.definition.modified_time != definition.modified_time
                    old_state.definition = definition
                    old_state.runtime_enabled = runtime_enabled
                    old_state.environment_ready = self._is_environment_ready(definition)
                    if definition_changed:
                        old_state.environment_preparing = False
                        old_state.environment_error = ""
                    self.states[name] = old_state
                else:
                    self.states[name] = CustomDataState(
                        definition=definition,
                        runtime_enabled=runtime_enabled,
                        environment_ready=self._is_environment_ready(definition),
                    )
                if runtime_enabled:
                    enabled_names.add(name)
                old_worker = old_workers.pop(name, None)
                if old_worker and old_worker.definition.modified_time == definition.modified_time:
                    old_worker.definition = definition
                    self.workers[name] = old_worker
                else:
                    if old_worker:
                        old_worker.stop()
                    self.workers[name] = CustomDataWorker(definition)
            for worker in old_workers.values():
                worker.stop()
            self.load_errors = errors
            self.last_scan_time = time.monotonic()
            self._runtime_enabled_names = enabled_names
            self._runtime_initialized = True

    def reload_if_changed(self):
        """检测插件入口、清单或目录列表变化，并在变化时自动重载。"""
        with self.lock:
            known = {(state.definition.path, state.definition.modified_time) for state in self.states.values()}
            current = set()
            for candidate in self._plugin_candidates():
                try:
                    definition = _load_definition(candidate, self.environment_root)
                    current.add((definition.path, definition.modified_time))
                except Exception:
                    self.reload_scripts()
                    return
            if known != current:
                self.reload_scripts()

    def environment_status(self, definition):
        """返回插件独立环境和依赖的中文状态。"""
        return "环境就绪" if self._is_environment_ready(definition) else self._environment_not_ready_status(definition)

    def _environment_not_ready_status(self, definition):
        """返回插件环境尚未达到可执行状态时的中文原因。"""
        python_path = _environment_python(definition.environment_directory)
        if not python_path.is_file():
            return "环境未安装"
        marker = definition.environment_directory / ".dependencies-ready"
        if definition.has_dependencies and (
            not marker.is_file() or marker.read_text(encoding="utf-8", errors="replace").strip() != self._requirements_digest(definition)
        ):
            return "依赖未安装"
        if not marker.is_file() or marker.read_text(encoding="utf-8", errors="replace").strip() != self._requirements_digest(definition):
            return "依赖状态未记录"
        return "环境未就绪"

    def _is_environment_ready(self, definition):
        """判断插件独立环境是否已经创建并安装当前 requirements.txt。"""
        python_path = _environment_python(definition.environment_directory)
        if not python_path.is_file():
            return False
        marker = definition.environment_directory / ".dependencies-ready"
        if not marker.is_file():
            return False
        try:
            return marker.read_text(encoding="utf-8", errors="replace").strip() == self._requirements_digest(definition)
        except OSError:
            return False

    def _requirements_digest(self, definition):
        """返回当前依赖声明的 SHA-256 摘要。"""
        if not definition.has_dependencies:
            return "无第三方依赖"
        return hashlib.sha256(definition.requirements_path.read_bytes()).hexdigest()

    def install_dependencies(self, name, progress_callback=None):
        """创建插件独立虚拟环境，并安装 requirements.txt 中的依赖。"""
        with self.lock:
            state = self.states.get(name)
            if state is None:
                raise CustomDataError("插件不存在或尚未加载")
            definition = state.definition
            worker = self.workers.get(name)
            if worker:
                worker.stop()
        runtime_python = get_runtime_python()
        if not runtime_python.is_file():
            raise CustomDataError("未找到插件 Python Runtime：{}".format(runtime_python))
        environment_python = _environment_python(definition.environment_directory)
        if not environment_python.is_file():
            if progress_callback:
                progress_callback("正在创建插件独立虚拟环境：{}".format(definition.environment_directory))
            self._run_install_command(
                [str(runtime_python), "-m", "venv", str(definition.environment_directory)],
                progress_callback,
            )
            if progress_callback:
                progress_callback("独立虚拟环境创建完成。")
        elif progress_callback:
            progress_callback("检测到已有独立虚拟环境，将继续检查依赖。")
        if definition.has_dependencies:
            if progress_callback:
                progress_callback("正在读取 requirements.txt 并执行 pip 安装……")
            self._run_install_command(
                [str(environment_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(definition.requirements_path)],
                progress_callback,
            )
            if progress_callback:
                progress_callback("requirements.txt 中的依赖安装完成。")
        elif progress_callback:
            progress_callback("插件未声明第三方依赖，无需执行 pip 安装。")
        (definition.environment_directory / ".dependencies-ready").write_text(
            self._requirements_digest(definition), encoding="utf-8", newline="\n"
        )
        if progress_callback:
            progress_callback("依赖状态已经记录，插件环境可以使用。")
        with self.lock:
            state = self.states.get(name)
            if state is not None:
                state.environment_ready = True
                state.environment_preparing = False
                state.environment_error = ""
        return self.environment_status(definition)

    def prepare_environments_async(self):
        """在后台为所有自定义数据插件创建独立执行环境。"""
        with self.lock:
            names = [
                name for name, state in self.states.items()
                if state.runtime_enabled
                and not state.environment_ready and not state.environment_preparing and not state.environment_error
            ]
            for name in names:
                state = self.states[name]
                state.environment_preparing = True
                state.environment_error = ""
                thread = threading.Thread(
                    target=self._prepare_environment_guarded,
                    args=(name,),
                    name="自定义数据环境准备-{}".format(name),
                    daemon=True,
                )
                self._environment_threads[name] = thread
                thread.start()

    def _prepare_environment_guarded(self, name):
        """隔离单个插件环境创建异常，并把失败原因写入插件状态。"""
        def log_progress(message):
            """把环境准备进度写入标准监控日志。"""
            logging.getLogger("pico-monitor.custom-data").info(
                "自定义数据环境准备：插件=%s，%s",
                name,
                message,
            )

        try:
            self.install_dependencies(name, log_progress)
        except Exception:
            error_text = traceback.format_exc()
            with self.lock:
                state = self.states.get(name)
                if state is not None:
                    state.environment_ready = False
                    state.environment_preparing = False
                    state.environment_error = error_text
            logging.getLogger("pico-monitor.custom-data").warning(
                "自定义数据环境准备失败：插件=%s，错误=%s",
                name,
                error_text,
            )
        finally:
            with self.lock:
                self._environment_threads.pop(name, None)

    def _run_install_command(self, command, progress_callback=None):
        """执行环境创建或 pip 安装命令，并逐行回传安装日志。"""
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        lines = []
        try:
            for line in process.stdout:
                lines.append(line)
                if progress_callback:
                    progress_callback(line.rstrip())
            return_code = process.wait()
        finally:
            process.stdout.close()
        if return_code != 0:
            raise CustomDataError("依赖安装失败：\n{}".format("".join(lines).strip()))

    def collect_due_data(self):
        """按各插件调用间隔执行到期任务，并返回 ext 字段映射。"""
        now = time.monotonic()
        self.reload_if_changed()
        with self.lock:
            for state in self.states.values():
                if not state.runtime_enabled:
                    continue
                configured_interval = self._plugin_configs.get(state.definition.name, {}).get(
                    "interval", state.definition.interval
                )
                if state.last_run_time and now - state.last_run_time < configured_interval:
                    continue
                try:
                    config = self._plugin_configs.get(state.definition.name, {"interval": state.definition.interval})
                    state.data = self.workers[state.definition.name].collect(config)
                    state.error = ""
                except Exception:
                    state.error = traceback.format_exc()
                finally:
                    state.last_run_time = now
            return {state.definition.key: state.data for state in self.states.values() if not state.error and state.data is not None}

    def collect_task_data(self, name):
        """通过独立常驻进程执行指定插件，且不阻塞其他插件采集。"""
        self.reload_if_changed()
        logger = logging.getLogger("pico-monitor.custom-data")
        with self.lock:
            state = self.states.get(name)
            if state is None:
                logger.warning("自定义数据插件不存在，跳过执行：插件=%s", name)
                return {}
            if not state.runtime_enabled:
                logger.info("自定义数据插件未加入当前运行任务，跳过执行：插件=%s", name)
                return {}
            if not state.environment_ready and self._is_environment_ready(state.definition):
                state.environment_ready = True
                state.environment_preparing = False
                state.environment_error = ""
            if not state.environment_ready:
                state.last_run_time = time.monotonic()
                state.error = state.environment_error or self._environment_not_ready_status(state.definition)
                logger.info(
                    "自定义数据插件环境未就绪，返回占位数据：插件=%s，数据键=%s，原因=%s",
                    state.definition.name,
                    state.definition.key,
                    state.error.splitlines()[-1] if state.error else "环境准备中",
                )
                return {state.definition.key: dict(CUSTOM_DATA_PLACEHOLDER)}
            definition = state.definition
            worker = self.workers[name]
            config = dict(self._plugin_configs.get(name, {"interval": definition.interval}))
        try:
            started = time.monotonic()
            logger.info(
                "自定义数据插件开始执行：插件=%s，中文名=%s，数据键=%s",
                definition.name,
                definition.zh_name,
                definition.key,
            )
            data = worker.collect(config)
            with self.lock:
                state.data = data
                state.error = ""
            logger.info(
                "自定义数据插件执行完成：插件=%s，耗时=%.3f秒",
                definition.name,
                time.monotonic() - started,
            )
            return {state.definition.key: data}
        except Exception:
            error_text = traceback.format_exc()
            with self.lock:
                state.error = error_text
            logger.warning(
                "自定义数据插件执行失败：插件=%s，错误=%s",
                definition.name,
                error_text,
            )
            return {}
        finally:
            with self.lock:
                state.last_run_time = time.monotonic()

    def task_definitions(self):
        """返回启动时可注册为采集任务的插件定义。"""
        self.reload_if_changed()
        with self.lock:
            return tuple(state.definition for state in self.states.values() if state.runtime_enabled)

    def list_definitions(self):
        """返回全部已加载插件定义，不受当前运行激活状态影响。"""
        self.reload_if_changed()
        with self.lock:
            return tuple(state.definition for state in self.states.values())

    def list_items(self):
        """返回管理窗口需要展示的插件状态和加载错误。"""
        self.reload_if_changed()
        with self.lock:
            return list(self.states.values()), dict(self.load_errors)

    def activate_plugin(self, name):
        """将指定插件加入当前运行的自定义数据采集任务。"""
        self.reload_if_changed()
        with self.lock:
            state = self.states.get(name)
            if state is None:
                raise CustomDataError("插件不存在或尚未加载：{}".format(name))
            state.runtime_enabled = True
            self._runtime_enabled_names.add(name)
            state.last_run_time = 0.0
            definition = state.definition
        logging.getLogger("pico-monitor.custom-data").info(
            "自定义数据插件已加入当前运行任务：插件=%s，任务=%s",
            name,
            definition.task_name,
        )
        self.prepare_environments_async()
        return definition

    def set_plugin_enabled(self, name, enabled):
        """设置一个插件的运行启用状态，并在禁用时停止其子进程。"""
        self.reload_if_changed()
        enabled = bool(enabled)
        with self.lock:
            state = self.states.get(name)
            if state is None:
                raise CustomDataError("插件不存在或尚未加载：{}".format(name))
            state.runtime_enabled = enabled
            state.last_run_time = 0.0
            if enabled:
                self._runtime_enabled_names.add(name)
            else:
                self._runtime_enabled_names.discard(name)
            worker = self.workers.get(name)
            definition = state.definition
        if not enabled and worker is not None:
            worker.stop()
        if enabled:
            self.prepare_environments_async()
        logging.getLogger("pico-monitor.custom-data").info(
            "自定义数据插件%s：插件=%s，任务=%s",
            "已启用" if enabled else "已停用",
            name,
            definition.task_name,
        )
        return definition

    def invoke_action(self, name, action_name, config=None):
        """在插件独立进程中执行清单动作并返回经过校验的结果。"""
        self.reload_if_changed()
        with self.lock:
            state = self.states.get(name)
            if state is None:
                raise CustomDataError("插件不存在或尚未加载：{}".format(name))
            definition = state.definition
            action = definition.action_map.get(action_name)
            if action is None:
                raise CustomDataError("插件未声明动作：{}".format(action_name))
            if not state.environment_ready and self._is_environment_ready(definition):
                state.environment_ready = True
            if not state.environment_ready:
                raise CustomDataError("插件环境尚未就绪，请先安装插件环境")
            normalized_config = _support.normalize_action_config(
                definition,
                config,
            )
            worker = self.workers[name]
        result = worker.invoke(
            action["method"],
            {"config": normalized_config, "action": action_name},
            action["timeout"],
        )
        return _support.normalize_action_result(definition, action_name, result)

    def _existing_identifiers(self, ignored_path=None):
        """返回除指定路径外已占用的数据 key 和任务名。"""
        ignored_path = Path(ignored_path).resolve() if ignored_path else None
        keys = {state.definition.key for state in self.states.values() if state.definition.plugin_directory.resolve() != ignored_path}
        names = {state.definition.name for state in self.states.values() if state.definition.plugin_directory.resolve() != ignored_path}
        return keys, names

    def _conflicting_definitions(self, definition, ignored_path=None):
        """返回与待导入插件数据 key 或任务名重复的已安装插件。"""
        ignored_path = Path(ignored_path).resolve() if ignored_path else None
        conflicts = []
        for state in self.states.values():
            installed = state.definition
            if ignored_path and installed.plugin_directory.resolve() == ignored_path:
                continue
            if installed.key == definition.key or installed.name == definition.name:
                conflicts.append(installed)
        return tuple(conflicts)

    def _remove_installed_definition(self, definition):
        """停止并移除一个已安装插件目录和对应独立环境。"""
        worker = self.workers.pop(definition.name, None)
        if worker:
            worker.stop()
        if definition.plugin_directory.is_dir():
            _rmtree_with_retry(definition.plugin_directory, "旧插件目录")
        if definition.environment_directory.is_dir():
            _rmtree_with_retry(definition.environment_directory, "旧插件独立环境")

    def import_plugin(self, source_path, overwrite=False):
        """从插件目录或 ZIP 包导入自定义数据插件。"""
        source_path = Path(source_path).resolve()
        if source_path.is_dir():
            source_root = source_path
            cleanup_root = None
        elif source_path.suffix.lower() == ".zip":
            import tempfile

            cleanup_root = tempfile.TemporaryDirectory()
            try:
                _safe_extract_zip(source_path, cleanup_root.name)
                source_root = _locate_manifest_root(cleanup_root.name)
            except Exception:
                cleanup_root.cleanup()
                raise
        else:
            raise CustomDataError("仅支持包含 plugin.json 的插件目录或 ZIP 插件包，不再支持单文件 .py 插件")
        try:
            definition = _load_definition(source_root, self.environment_root)
            target = self.custom_directory / definition.name
            if source_root.resolve() == target.resolve():
                self.reload_scripts()
                if definition.name not in self.states:
                    raise CustomDataError("插件已在目标目录中，但当前未能成功加载：{}".format(definition.name))
                return self.states[definition.name].definition
            conflicts = self._conflicting_definitions(definition)
            target_conflicts = target.exists()
            if (conflicts or target_conflicts) and not overwrite:
                conflict_text = "、".join(
                    "{}(key={}，task={})".format(conflict.zh_name, conflict.key, conflict.task_name)
                    for conflict in conflicts
                )
                if target_conflicts and target.resolve() not in {conflict.plugin_directory.resolve() for conflict in conflicts}:
                    target_text = "目标目录已存在但当前未加载：{}".format(target)
                    conflict_text = "、".join(filter(None, (conflict_text, target_text)))
                raise CustomDataDuplicateError(
                    "插件重复：{}。确认覆盖后会替换这些已安装插件。".format(conflict_text),
                    definition,
                    conflicts,
                )
            if overwrite:
                removed_paths = set()
                for conflict in conflicts:
                    removed_paths.add(conflict.plugin_directory.resolve())
                    self._remove_installed_definition(conflict)
                if target.exists() and target.resolve() not in removed_paths:
                    _rmtree_with_retry(target, "目标插件目录")
                if definition.environment_directory.is_dir():
                    _rmtree_with_retry(definition.environment_directory, "目标插件独立环境")
            if target.exists():
                raise CustomDataError("目标插件已存在：{}".format(definition.name))
            shutil.copytree(source_root, target, ignore=shutil.ignore_patterns(".venv", "venv", "__pycache__", "*.pyc"))
        finally:
            if cleanup_root is not None:
                cleanup_root.cleanup()
        self.reload_scripts()
        with self.lock:
            state = self.states[definition.name]
            state.runtime_enabled = False
            self._runtime_enabled_names.discard(definition.name)
            return state.definition

    def delete_plugin(self, plugin_path, config=None):
        """执行可选卸载钩子后删除指定插件及其独立环境。"""
        plugin_path = Path(plugin_path).resolve()
        if plugin_path.parent != self.custom_directory.resolve():
            raise CustomDataError("只能删除 customData 目录内的插件")
        definition = None
        for state in self.states.values():
            if state.definition.plugin_directory.resolve() == plugin_path or state.definition.path.resolve() == plugin_path:
                definition = state.definition
                break
        if definition is None:
            raise CustomDataError("未找到要删除的插件")
        worker = self.workers.get(definition.name)
        if definition.has_uninstall:
            state = self.states[definition.name]
            if not state.environment_ready and self._is_environment_ready(definition):
                state.environment_ready = True
            if not state.environment_ready:
                raise CustomDataError("插件声明了 uninstall 清理钩子，请先安装插件环境后再删除")
            normalized_config = _support.normalize_plugin_configs(
                {definition.name: config or {}},
                (definition,),
            )[definition.name]
            worker.uninstall(
                {
                    "config": normalized_config,
                    "reason": "delete",
                    "plugin_directory": str(definition.plugin_directory),
                }
            )
        if worker:
            worker.stop()
        _rmtree_with_retry(definition.plugin_directory, "插件目录")
        if definition.environment_directory.is_dir():
            _rmtree_with_retry(definition.environment_directory, "插件独立环境")
        self.reload_scripts()

    def test_plugin(self, name):
        """测试执行指定插件并返回格式化 JSON 或中文错误详情。"""
        with self.lock:
            state = self.states.get(name)
            if state is None:
                return "插件不存在或尚未加载"
            worker = self.workers[name]
        try:
            config = dict(self._plugin_configs.get(name, {"interval": state.definition.interval}))
            result = worker.collect(config)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception:
            return traceback.format_exc()

_manager = None


def get_manager():
    """返回进程内共享的自定义数据管理器单例。"""
    global _manager
    if _manager is None:
        _manager = CustomDataManager()
    return _manager


def custom_data_task_defaults():
    """返回自定义数据任务完整标识到默认采集频率的映射。"""
    return {definition.task_name: definition.interval for definition in get_manager().task_definitions()}


def custom_data_task_zh_names():
    """返回自定义数据任务完整标识到中文名称的映射。"""
    return {definition.task_name: definition.zh_name for definition in get_manager().task_definitions()}
