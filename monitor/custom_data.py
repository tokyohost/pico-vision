#!/usr/bin/env python3
"""管理 monitor 自定义数据脚本的加载、校验、执行和结果缓存。"""

import importlib.util
import json
import os
import shutil
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path


CUSTOM_DATA_DIRECTORY_NAME = "customData"
CUSTOM_DATA_TEMPLATE_NAME = "custom_data_template.py"
CUSTOM_DATA_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
CUSTOM_DATA_TASK_PREFIX = "custom_data."
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 10.0

TEMPLATE_CONTENT = '''#!/usr/bin/env python3
"""自定义数据采集脚本模板。"""

import datetime as dt


# JSON 中 ext 节点下使用的字段名，必须在所有自定义脚本中唯一。
CUSTOM_DATA_KEY = "my_data"

# 采集任务英文标识，用于 collection_tasks.intervals 配置，必须在所有自定义脚本中唯一。
CUSTOM_DATA_NAME = "my_data"

# 采集任务中文名称，用于 Windows 配置页和日志展示。
CUSTOM_DATA_ZH_NAME = "我的数据"

# monitor 调用 collect 的间隔，单位为秒，必须大于 0。
CUSTOM_DATA_INTERVAL = 5


def collect():
    """采集用户自定义数据并返回可 JSON 序列化的对象。"""
    return {
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "value": 0,
    }
'''


@dataclass(frozen=True)
class CustomDataDefinition:
    """保存已通过校验的自定义数据脚本定义。"""

    path: Path
    key: str
    name: str
    zh_name: str
    interval: float
    modified_time: float

    @property
    def task_name(self):
        """返回调度器使用的完整自定义数据任务标识。"""
        return CUSTOM_DATA_TASK_PREFIX + self.name


@dataclass
class CustomDataState:
    """保存单个自定义数据脚本的运行状态和最近结果。"""

    definition: CustomDataDefinition
    last_run_time: float = 0.0
    data: object = None
    error: str = ""


class CustomDataError(Exception):
    """表示自定义数据脚本校验或执行失败。"""


def get_custom_data_directory():
    """返回自定义数据脚本目录，并在首次使用时自动创建目录和模板。"""
    data_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PicoMonitor"
    custom_directory = data_root / CUSTOM_DATA_DIRECTORY_NAME
    custom_directory.mkdir(parents=True, exist_ok=True)
    template_path = custom_directory / CUSTOM_DATA_TEMPLATE_NAME
    if not template_path.exists():
        template_path.write_text(TEMPLATE_CONTENT, encoding="utf-8", newline="\n")
    return custom_directory


def _load_module_from_path(script_path):
    """从指定 py 文件路径加载一个独立模块实例。"""
    module_name = f"pico_custom_data_{abs(hash(script_path))}_{time.time_ns()}"
    specification = importlib.util.spec_from_file_location(module_name, script_path)
    if specification is None or specification.loader is None:
        raise CustomDataError("无法加载脚本模块")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _validate_json_serializable(value):
    """校验脚本返回值是否可以转换为 JSON。"""
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise CustomDataError(f"collect 返回值不是合法 JSON 数据：{error}") from error


def validate_script(script_path, existing_keys=None, existing_names=None):
    """校验自定义数据脚本格式、任务名称、key 唯一性和返回值类型。"""
    import re

    script_path = Path(script_path).resolve()
    if script_path.suffix.lower() != ".py":
        raise CustomDataError("只能加载 .py 文件")
    if not script_path.is_file():
        raise CustomDataError("脚本文件不存在")

    module = _load_module_from_path(script_path)
    key = getattr(module, "CUSTOM_DATA_KEY", None)
    if not isinstance(key, str) or not key:
        raise CustomDataError("必须定义非空字符串 CUSTOM_DATA_KEY")
    if re.match(CUSTOM_DATA_KEY_PATTERN, key) is None:
        raise CustomDataError("CUSTOM_DATA_KEY 只能包含字母、数字和下划线，且不能以数字开头")
    if existing_keys and key in existing_keys:
        raise CustomDataError(f"CUSTOM_DATA_KEY 重复：{key}")

    name = getattr(module, "CUSTOM_DATA_NAME", key)
    if not isinstance(name, str) or not name:
        raise CustomDataError("必须定义非空字符串 CUSTOM_DATA_NAME")
    if re.match(CUSTOM_DATA_KEY_PATTERN, name) is None:
        raise CustomDataError("CUSTOM_DATA_NAME 只能包含字母、数字和下划线，且不能以数字开头")
    if existing_names and name in existing_names:
        raise CustomDataError(f"CUSTOM_DATA_NAME 重复：{name}")

    zh_name = getattr(module, "CUSTOM_DATA_ZH_NAME", None)
    if not isinstance(zh_name, str) or not zh_name.strip():
        zh_name = name
    zh_name = zh_name.strip()

    interval = getattr(module, "CUSTOM_DATA_INTERVAL", None)
    if not isinstance(interval, (int, float)) or interval <= 0:
        raise CustomDataError("必须定义大于 0 的 CUSTOM_DATA_INTERVAL")
    if not callable(getattr(module, "collect", None)):
        raise CustomDataError("必须定义 collect() 方法")

    result = module.collect()
    _validate_json_serializable(result)
    return CustomDataDefinition(
        path=script_path,
        key=key,
        name=name,
        zh_name=zh_name,
        interval=float(interval),
        modified_time=script_path.stat().st_mtime,
    )


def run_script(definition):
    """执行指定自定义数据脚本并返回 collect 的 JSON 数据。"""
    module = _load_module_from_path(definition.path)
    collect = getattr(module, "collect", None)
    if not callable(collect):
        raise CustomDataError("collect() 方法不存在")
    result = collect()
    _validate_json_serializable(result)
    return result


class CustomDataManager:
    """协调自定义数据脚本扫描、去重、按间隔执行和结果读取。"""

    def __init__(self, custom_directory=None):
        """初始化自定义数据目录、脚本状态表和线程锁。"""
        self.custom_directory = Path(custom_directory) if custom_directory else get_custom_data_directory()
        self.lock = threading.RLock()
        self.states = {}
        self.load_errors = {}
        self.last_scan_time = 0.0
        self.reload_scripts()

    def reload_scripts(self):
        """重新扫描目录下所有 py 文件并校验脚本 key 是否重复。"""
        with self.lock:
            definitions = {}
            names = set()
            errors = {}
            for script_path in sorted(self.custom_directory.glob("*.py")):
                if script_path.name == CUSTOM_DATA_TEMPLATE_NAME:
                    continue
                try:
                    definition = validate_script(
                        script_path,
                        existing_keys={item.key for item in definitions.values()},
                        existing_names=names,
                    )
                    definitions[definition.name] = definition
                    names.add(definition.name)
                except Exception as error:
                    errors[str(script_path)] = traceback.format_exception_only(type(error), error)[-1].strip()

            old_states = self.states
            self.states = {}
            for name, definition in definitions.items():
                old_state = old_states.get(name)
                if old_state and old_state.definition.path == definition.path:
                    old_state.definition = definition
                    self.states[name] = old_state
                else:
                    self.states[name] = CustomDataState(definition=definition)
            self.load_errors = errors
            self.last_scan_time = time.monotonic()

    def reload_if_changed(self):
        """检测脚本文件列表或修改时间变化，并在变化时自动重载。"""
        with self.lock:
            paths = {state.definition.path: state.definition.modified_time for state in self.states.values()}
            current_paths = {
                path.resolve(): path.stat().st_mtime
                for path in self.custom_directory.glob("*.py")
                if path.name != CUSTOM_DATA_TEMPLATE_NAME
            }
            if paths != current_paths:
                self.reload_scripts()

    def collect_due_data(self):
        """按各脚本调用间隔执行到期脚本，并返回 ext 字段需要的 key-data 映射。"""
        now = time.monotonic()
        self.reload_if_changed()
        with self.lock:
            for state in self.states.values():
                if state.last_run_time and now - state.last_run_time < state.definition.interval:
                    continue
                try:
                    state.data = run_script(state.definition)
                    state.error = ""
                except Exception:
                    state.error = traceback.format_exc()
                finally:
                    state.last_run_time = now
            return {
                state.definition.key: state.data
                for state in self.states.values()
                if state.error == "" and state.data is not None
            }

    def collect_task_data(self, name):
        """执行指定自定义数据任务，并返回 ext 字段需要合并的 key-data 映射。"""
        self.reload_if_changed()
        with self.lock:
            state = self.states.get(name)
            if state is None:
                return {}
            try:
                state.data = run_script(state.definition)
                state.error = ""
                return {state.definition.key: state.data}
            except Exception:
                state.error = traceback.format_exc()
                return {}
            finally:
                state.last_run_time = time.monotonic()

    def task_definitions(self):
        """返回启动时可注册为采集任务的自定义数据脚本定义。"""
        self.reload_if_changed()
        with self.lock:
            return tuple(state.definition for state in self.states.values())

    def list_items(self):
        """返回弹窗列表需要展示的脚本定义和加载错误。"""
        self.reload_if_changed()
        with self.lock:
            items = list(self.states.values())
            errors = dict(self.load_errors)
        return items, errors

    def import_script(self, source_path):
        """复制用户选择的 py 文件到 customData 目录并完成格式校验。"""
        source_path = Path(source_path).resolve()
        existing_keys = {
            state.definition.key
            for state in self.states.values()
            if state.definition.path.resolve() != source_path
        }
        existing_names = {
            state.definition.name
            for state in self.states.values()
            if state.definition.path.resolve() != source_path
        }
        definition = validate_script(
            source_path,
            existing_keys=existing_keys,
            existing_names=existing_names,
        )
        target_path = self.custom_directory / source_path.name
        if target_path.resolve() != source_path:
            if target_path.exists():
                raise CustomDataError(f"目标文件已存在：{target_path.name}")
            shutil.copy2(source_path, target_path)
            definition = validate_script(
                target_path,
                existing_keys=existing_keys,
                existing_names=existing_names,
            )
        self.reload_scripts()
        return definition

    def delete_script(self, script_path):
        """删除指定自定义数据脚本并重新加载脚本列表。"""
        script_path = Path(script_path).resolve()
        if script_path.parent != self.custom_directory.resolve():
            raise CustomDataError("只能删除 customData 目录内的脚本")
        if script_path.name == CUSTOM_DATA_TEMPLATE_NAME:
            raise CustomDataError("不能删除基础模板")
        script_path.unlink(missing_ok=True)
        self.reload_scripts()

    def test_script(self, script_path):
        """测试执行指定脚本并返回格式化后的 JSON 或错误详情。"""
        try:
            keys = {
                state.definition.key
                for state in self.states.values()
                if state.definition.path.resolve() != Path(script_path).resolve()
            }
            names = {
                state.definition.name
                for state in self.states.values()
                if state.definition.path.resolve() != Path(script_path).resolve()
            }
            definition = validate_script(script_path, existing_keys=keys, existing_names=names)
            result = run_script(definition)
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
    return {
        definition.task_name: definition.interval
        for definition in get_manager().task_definitions()
    }


def custom_data_task_zh_names():
    """返回自定义数据任务完整标识到中文名称的映射。"""
    return {
        definition.task_name: definition.zh_name
        for definition in get_manager().task_definitions()
    }
