#!/usr/bin/env python3
"""管理 Monitor 自定义数据插件的导入、依赖环境、执行和结果缓存。"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from collectTask.executor import BoundedElasticThreadPool, TaskRejectedError
from collectTask.system_tasks import CollectionTask


CUSTOM_DATA_DIRECTORY_NAME = "customData"
CUSTOM_DATA_ENVIRONMENT_DIRECTORY_NAME = "pluginEnvs"
CUSTOM_DATA_MANIFEST_NAME = "plugin.json"
CUSTOM_DATA_REQUIREMENTS_NAME = "requirements.txt"
CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME = "custom_data_plugin_template"
CUSTOM_DATA_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
CUSTOM_DATA_TASK_PREFIX = "custom_data."
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 10.0
PLUGIN_PROTOCOL_VERSION = 1
CUSTOM_DATA_PLACEHOLDER = {"status": "pending", "message": "自定义数据环境准备中"}
CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS = 1
CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS = 5
CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY = 100
CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS = 1.0
CUSTOM_DATA_REMOVE_RETRY_COUNT = 8
CUSTOM_DATA_REMOVE_RETRY_DELAY_SECONDS = 0.25

TEMPLATE_MANIFEST_CONTENT = '''{
  "protocol": 1,
  "key": "my_data",
  "name": "my_data",
  "zh_name": "我的数据",
  "interval": 5,
  "entry": "main.py"
}
'''

TEMPLATE_SCRIPT_CONTENT = '''#!/usr/bin/env python3
"""自定义数据插件入口模板。"""

import datetime as dt


def collect():
    """采集自定义数据并返回可进行 JSON 序列化的对象。"""
    return {
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "value": 0,
    }
'''

@dataclass(frozen=True)
class CustomDataDefinition:
    """保存已通过校验的自定义数据插件定义。"""

    path: Path
    plugin_directory: Path
    key: str
    name: str
    zh_name: str
    interval: float
    modified_time: float
    requirements_path: Path = None
    environment_directory: Path = None

    @property
    def task_name(self):
        """返回调度器使用的完整自定义数据任务标识。"""
        return CUSTOM_DATA_TASK_PREFIX + self.name

    @property
    def has_dependencies(self):
        """返回插件是否声明了需要安装的第三方依赖。"""
        if not self.requirements_path or not self.requirements_path.is_file():
            return False
        lines = self.requirements_path.read_text(encoding="utf-8-sig").splitlines()
        return any(line.strip() and not line.lstrip().startswith("#") for line in lines)


@dataclass
class CustomDataState:
    """保存单个自定义数据插件的运行状态和最近结果。"""

    definition: CustomDataDefinition
    runtime_enabled: bool = True
    last_run_time: float = 0.0
    data: object = None
    error: str = ""
    environment_ready: bool = False
    environment_preparing: bool = False
    environment_error: str = ""


class CustomDataError(Exception):
    """表示自定义数据插件校验、安装或执行失败。"""


class CustomDataDuplicateError(CustomDataError):
    """表示导入插件的数据 key 或任务名与现有插件冲突。"""

    def __init__(self, message, definition, conflicts):
        """保存待导入插件定义和冲突的已安装插件定义。"""
        super().__init__(message)
        self.definition = definition
        self.conflicts = tuple(conflicts)


def get_data_root():
    """返回 Monitor 当前用户数据根目录。"""
    configured_root = os.environ.get("PICO_MONITOR_DATA_ROOT")
    if configured_root:
        return Path(configured_root).expanduser()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "PicoMonitor"
    return Path.home() / "PicoMonitor"


def get_custom_data_directory():
    """返回插件目录，并在首次使用时创建标准目录插件模板。"""
    custom_directory = get_data_root() / CUSTOM_DATA_DIRECTORY_NAME
    custom_directory.mkdir(parents=True, exist_ok=True)
    _create_plugin_template(custom_directory)
    return custom_directory


def _create_plugin_template(custom_directory):
    """创建不会参与扫描的标准目录插件模板，并保留用户已经修改的文件。"""
    template_directory = Path(custom_directory) / CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME
    template_directory.mkdir(parents=True, exist_ok=True)
    template_files = {
        CUSTOM_DATA_MANIFEST_NAME: TEMPLATE_MANIFEST_CONTENT,
        "main.py": TEMPLATE_SCRIPT_CONTENT,
        CUSTOM_DATA_REQUIREMENTS_NAME: "# 在此按行填写插件依赖，例如 requests==2.32.3。\n",
    }
    for filename, content in template_files.items():
        target = template_directory / filename
        if not target.exists():
            target.write_text(content, encoding="utf-8", newline="\n")


def get_environment_root():
    """返回保存插件独立虚拟环境的根目录。"""
    environment_root = get_data_root() / CUSTOM_DATA_ENVIRONMENT_DIRECTORY_NAME
    environment_root.mkdir(parents=True, exist_ok=True)
    return environment_root


def get_runtime_python():
    """返回用于创建和运行插件环境的完整 Python 解释器。"""
    configured = os.environ.get("PICO_MONITOR_PLUGIN_PYTHON")
    if configured:
        return Path(configured)
    if sys.platform == "win32":
        executable_directory = Path(sys.executable).resolve().parent
        for bundled in (
            executable_directory / "plugin-runtime" / "python.exe",
            executable_directory / "plugin-runtime" / "Scripts" / "python.exe",
        ):
            if bundled.is_file():
                return bundled
    return Path(sys.executable).resolve()


def _environment_python(environment_directory):
    """返回指定虚拟环境中的 Python 解释器路径。"""
    if sys.platform == "win32":
        return Path(environment_directory) / "Scripts" / "python.exe"
    return Path(environment_directory) / "bin" / "python"


def _runner_path():
    """返回插件子进程入口脚本路径，并兼容 PyInstaller 数据目录。"""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / "custom_data_runner.py"


def _validate_identifier(value, field_name):
    """校验插件英文标识并返回原值。"""
    import re

    if not isinstance(value, str) or not value:
        raise CustomDataError("必须定义非空字符串 {}".format(field_name))
    if re.match(CUSTOM_DATA_KEY_PATTERN, value) is None:
        raise CustomDataError("{} 只能包含字母、数字和下划线，且不能以数字开头".format(field_name))
    return value


def _load_definition(plugin_path, environment_root):
    """从插件目录读取并校验插件定义。"""
    plugin_path = Path(plugin_path).resolve()
    if not plugin_path.is_dir():
        raise CustomDataError("自定义数据插件必须是包含 plugin.json 的目录")
    manifest_path = plugin_path / CUSTOM_DATA_MANIFEST_NAME
    try:
        values = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError) as error:
        raise CustomDataError("plugin.json 读取失败：{}".format(error)) from error
    if values.get("protocol", PLUGIN_PROTOCOL_VERSION) != PLUGIN_PROTOCOL_VERSION:
        raise CustomDataError("plugin.json protocol 版本不受支持")
    entry = values.get("entry", "main.py")
    if not isinstance(entry, str) or Path(entry).name != entry or not entry.lower().endswith(".py"):
        raise CustomDataError("plugin.json entry 必须是插件根目录内的 py 文件名")
    script_path = plugin_path / entry
    if not script_path.is_file():
        raise CustomDataError("插件入口文件不存在：{}".format(entry))
    plugin_directory = plugin_path
    requirements_path = plugin_path / CUSTOM_DATA_REQUIREMENTS_NAME
    key = _validate_identifier(values.get("CUSTOM_DATA_KEY", values.get("key")), "CUSTOM_DATA_KEY")
    name = _validate_identifier(values.get("CUSTOM_DATA_NAME", values.get("name", key)), "CUSTOM_DATA_NAME")
    zh_name = values.get("CUSTOM_DATA_ZH_NAME", values.get("zh_name", name))
    if not isinstance(zh_name, str) or not zh_name.strip():
        zh_name = name
    interval = values.get("CUSTOM_DATA_INTERVAL", values.get("interval"))
    if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
        raise CustomDataError("必须定义大于 0 的 CUSTOM_DATA_INTERVAL")
    tracked_paths = [
        path for path in plugin_directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix.lower() not in (".pyc", ".pyo")
    ]
    modified_time = max(path.stat().st_mtime for path in tracked_paths)
    return CustomDataDefinition(
        path=script_path,
        plugin_directory=plugin_directory,
        key=key,
        name=name,
        zh_name=zh_name.strip(),
        interval=float(interval),
        modified_time=modified_time,
        requirements_path=requirements_path,
        environment_directory=Path(environment_root) / name,
    )


def _validate_uniqueness(definition, existing_keys=None, existing_names=None):
    """校验插件数据 key 和任务名是否与现有插件重复。"""
    if existing_keys and definition.key in existing_keys:
        raise CustomDataError("CUSTOM_DATA_KEY 重复：{}".format(definition.key))
    if existing_names and definition.name in existing_names:
        raise CustomDataError("CUSTOM_DATA_NAME 重复：{}".format(definition.name))


def _safe_extract_zip(archive_path, target_directory):
    """安全解压插件 ZIP，拒绝绝对路径、路径穿越和符号链接。"""
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > 2000 or sum(member.file_size for member in members) > 50 * 1024 * 1024:
            raise CustomDataError("ZIP 插件包解压后不能超过 50 MB 或 2000 个文件")
        for member in members:
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise CustomDataError("ZIP 包包含不安全路径：{}".format(member.filename))
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise CustomDataError("ZIP 包不能包含符号链接")
        archive.extractall(target_directory)


def _locate_manifest_root(extracted_directory):
    """在解压目录中定位唯一的插件清单根目录。"""
    manifests = list(Path(extracted_directory).rglob(CUSTOM_DATA_MANIFEST_NAME))
    if len(manifests) != 1:
        raise CustomDataError("ZIP 插件包必须且只能包含一个 plugin.json")
    return manifests[0].parent


def _retry_remove_readonly(function, path, exc_info):
    """在删除只读文件失败时临时增加写权限并重试。"""
    del exc_info
    try:
        os.chmod(path, 0o700)
        function(path)
    except OSError:
        raise


def _rmtree_with_retry(path, description):
    """删除目录，并兼容 Windows 刚释放进程句柄时的短暂占用。"""
    path = Path(path)
    if not path.exists():
        return
    last_error = None
    for attempt in range(CUSTOM_DATA_REMOVE_RETRY_COUNT):
        try:
            shutil.rmtree(path, onerror=_retry_remove_readonly)
            return
        except OSError as error:
            last_error = error
            if attempt + 1 >= CUSTOM_DATA_REMOVE_RETRY_COUNT:
                break
            time.sleep(CUSTOM_DATA_REMOVE_RETRY_DELAY_SECONDS)
    raise CustomDataError(
        "无法删除{}：{}。可能仍有窗口、插件进程或杀毒软件正在占用，请稍后重试。原始错误：{}".format(
            description,
            path,
            last_error,
        )
    ) from last_error


class CustomDataWorker:
    """维护单个插件的常驻隔离进程，避免高频采集反复启动解释器。"""

    def __init__(self, definition):
        """保存插件定义并初始化尚未启动的进程状态。"""
        self.definition = definition
        self.process = None
        self.lock = threading.RLock()

    def _start(self):
        """启动插件常驻进程并建立行式 JSON 通信管道。"""
        python_path = _environment_python(self.definition.environment_directory)
        if not python_path.is_file():
            raise CustomDataError("插件环境尚未安装，请先在自定义数据窗口安装依赖")
        self.process = subprocess.Popen(
            [str(python_path), str(_runner_path()), str(self.definition.path)],
            cwd=str(self.definition.plugin_directory), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def collect(self, timeout=DEFAULT_SCRIPT_TIMEOUT_SECONDS):
        """请求常驻进程执行一次采集，超时或退出时终止进程以便下次重建。"""
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.stop()
                self._start()
            try:
                self.process.stdin.write('{"command":"collect"}\n')
                self.process.stdin.flush()
                result = []
                reader = threading.Thread(target=lambda: result.append(self.process.stdout.readline()), daemon=True)
                reader.start()
                reader.join(timeout)
                if reader.is_alive():
                    self.stop()
                    raise CustomDataError("collect 执行超过 {:g} 秒，已重启插件进程".format(timeout))
                if not result or not result[0]:
                    self.stop()
                    raise CustomDataError("插件进程异常退出")
                envelope = json.loads(result[0])
            except (OSError, ValueError) as error:
                self.stop()
                raise CustomDataError("插件进程通信失败：{}".format(error)) from error
            if not envelope.get("ok"):
                raise CustomDataError(envelope.get("error", "插件执行失败"))
            return envelope.get("data")

    def stop(self):
        """终止插件进程并关闭通信管道。"""
        with self.lock:
            process, self.process = self.process, None
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


class CustomDataCollectionTask(CollectionTask):
    """把单个自定义数据插件封装为标准采集任务。"""

    order = 2000

    def __init__(self, manager, definition):
        """保存插件管理器和插件定义，并设置任务标识、中文名和频率。"""
        super().__init__(manager)
        self.manager = manager
        self.definition = definition
        self.plugin_name = definition.name
        self.name = definition.task_name
        self.zh_name = definition.zh_name
        self.default_interval = float(definition.interval)
        self.interval = float(definition.interval)

    def update_definition(self, definition):
        """更新插件定义，并同步默认采集频率和中文名称。"""
        self.definition = definition
        self.plugin_name = definition.name
        self.name = definition.task_name
        self.zh_name = definition.zh_name
        self.default_interval = float(definition.interval)
        self.interval = float(definition.interval)

    def collect(self):
        """执行插件采集并返回可合并到完整快照的 ext 片段。"""
        return {"ext": self.manager.collect_task_data(self.plugin_name)}


class CustomDataCollectionCoordinator:
    """使用独立线程池调度全部自定义数据采集任务。"""

    def __init__(
        self,
        manager,
        result_store,
        result_transform=None,
        task_intervals=None,
        task_logs_enabled=True,
    ):
        """创建核心 1、最大 5、队列 100 的自定义数据采集协调器。"""
        self.manager = manager
        self.result_store = result_store
        self.result_transform = result_transform
        self.task_logs_enabled = bool(task_logs_enabled)
        self.task_intervals = dict(task_intervals or {})
        self.tasks = ()
        self.executor = BoundedElasticThreadPool(
            core_workers=CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS,
            max_workers=CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS,
            queue_capacity=CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY,
        )
        self._sync_tasks()
        self.manager.prepare_environments_async()
        LOGGER = logging.getLogger("pico-monitor.custom-data")
        if self.task_logs_enabled:
            LOGGER.info("自定义数据采集线程池已初始化：%s", self._pool_state_text())
            LOGGER.info("自定义数据采集任务频率：%s", self._task_interval_text() or "无")

    def schedule(self):
        """提交当前到期且未在执行的自定义数据任务，队列饱和时丢弃。"""
        self._sync_tasks()
        self.manager.prepare_environments_async()
        now = time.monotonic()
        logger = logging.getLogger("pico-monitor.custom-data")
        for task in self.tasks:
            if not task.is_due(now):
                continue
            task.mark_scheduled(now)
            try:
                self.executor.submit(self._execute_and_publish, task)
                if self.task_logs_enabled:
                    logger.debug(
                        "自定义数据任务已提交：任务=%s，频率=%.3f秒，%s",
                        self._task_label(task),
                        task.interval,
                        self._pool_state_text(),
                    )
            except TaskRejectedError:
                task.mark_finished()
                logger.warning("自定义数据任务被丢弃：任务=%s，%s", self._task_label(task), self._pool_state_text())

    def activate_plugin(self, name):
        """将指定插件加入当前协调器，并把首次采集时间提前到现在。"""
        definition = self.manager.activate_plugin(name)
        self._sync_tasks()
        for task in self.tasks:
            if task.plugin_name == definition.name:
                task.next_run_time = 0.0
                break
        return definition

    def next_schedule_delay(self):
        """返回下一次自定义数据任务到期前需要等待的秒数。"""
        now = time.monotonic()
        due_times = [task.next_run_time for task in self.tasks if not task.scheduled]
        if not due_times:
            return min((task.interval for task in self.tasks), default=1.0)
        return max(0.0, min(due_times) - now)

    def close(self, wait=True):
        """关闭自定义数据采集线程池。"""
        if self.task_logs_enabled:
            logging.getLogger("pico-monitor.custom-data").info("自定义数据采集线程池准备关闭：%s", self._pool_state_text())
        self.executor.shutdown(wait=wait)
        if self.task_logs_enabled:
            logging.getLogger("pico-monitor.custom-data").info("自定义数据采集线程池已关闭：%s", self._pool_state_text())

    def _sync_tasks(self):
        """根据插件目录最新定义同步采集任务列表。"""
        existing = {task.plugin_name: task for task in self.tasks}
        tasks = []
        for definition in self.manager.task_definitions():
            task = existing.get(definition.name)
            if task is None:
                task = CustomDataCollectionTask(self.manager, definition)
            else:
                task.update_definition(definition)
            configured_interval = self.task_intervals.get(task.name)
            if configured_interval is not None:
                try:
                    task.configure_interval(configured_interval)
                except (TypeError, ValueError):
                    logging.getLogger("pico-monitor.custom-data").warning(
                        "忽略无效自定义数据采集频率配置：任务=%s，频率=%s",
                        task.name,
                        configured_interval,
                    )
            tasks.append(task)
        self.tasks = tuple(tasks)

    def _execute_and_publish(self, task):
        """执行单个自定义数据任务并发布快照片段。"""
        started = time.monotonic()
        task_label = self._task_label(task)
        logger = logging.getLogger("pico-monitor.custom-data")
        if self.task_logs_enabled:
            logger.debug("自定义数据任务开始：任务=%s，%s", task_label, self._pool_state_text())
        try:
            fragment = task.collect()
            if self.result_transform is not None:
                fragment = self.result_transform(fragment)
            self.result_store.publish(fragment)
            elapsed = time.monotonic() - started
            is_slow_task = elapsed >= CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS
            if self.task_logs_enabled or is_slow_task:
                log_method = logger.warning if is_slow_task else logger.debug
                log_method(
                    "自定义数据任务完成：任务=%s，耗时=%.3f秒，更新字段=%s，%s",
                    task_label,
                    elapsed,
                    "、".join(fragment.keys()) or "无",
                    self._pool_state_text(),
                )
        except Exception as error:
            logger.exception(
                "自定义数据任务失败：任务=%s，耗时=%.3f秒，错误=%s，%s",
                task_label,
                time.monotonic() - started,
                error,
                self._pool_state_text(),
            )
        finally:
            task.mark_finished()
            task.scheduled = False

    def _task_interval_text(self):
        """把所有自定义数据任务当前采集频率格式化为日志文本。"""
        return "、".join("{}={}秒".format(self._task_label(task), task.interval) for task in self.tasks)

    def _pool_state_text(self):
        """把自定义数据采集线程池状态格式化为中文日志文本。"""
        state = self.executor.state()
        return (
            "线程池[核心={core_workers}，最大={max_workers}，已创建={workers}，"
            "活跃={active}，空闲={idle}，排队={queued}/{queue_capacity}]"
        ).format(**state)

    @staticmethod
    def _task_label(task):
        """返回日志中使用的自定义数据任务中文名称和英文标识。"""
        return "{}({})".format(task.zh_name, task.name) if task.zh_name != task.name else task.name


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
        self._runtime_enabled_names = set()
        self._runtime_initialized = False
        self.reload_scripts()

    def close(self):
        """停止全部插件常驻进程并释放通信管道。"""
        with self.lock:
            workers, self.workers = tuple(self.workers.values()), {}
        for worker in workers:
            worker.stop()

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
                if state.last_run_time and now - state.last_run_time < state.definition.interval:
                    continue
                try:
                    state.data = self.workers[state.definition.name].collect()
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
        try:
            started = time.monotonic()
            logger.info(
                "自定义数据插件开始执行：插件=%s，中文名=%s，数据键=%s",
                definition.name,
                definition.zh_name,
                definition.key,
            )
            data = worker.collect()
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

    def delete_plugin(self, plugin_path):
        """删除指定插件及其独立虚拟环境。"""
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
            result = worker.collect()
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
