#!/usr/bin/env python3
"""管理 Monitor 自定义数据插件的导入、依赖环境、执行和结果缓存。"""

import json
import os
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

CUSTOM_DATA_DIRECTORY_NAME = "customData"
CUSTOM_DATA_ENVIRONMENT_DIRECTORY_NAME = "pluginEnvs"
CUSTOM_DATA_MANIFEST_NAME = "plugin.json"
CUSTOM_DATA_REQUIREMENTS_NAME = "requirements.txt"
CUSTOM_DATA_TEMPLATE_DIRECTORY_NAME = "custom_data_plugin_template"
CUSTOM_DATA_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
CUSTOM_DATA_TASK_PREFIX = "custom_data."
DEFAULT_SCRIPT_TIMEOUT_SECONDS = 10.0
PLUGIN_PROTOCOL_VERSION = 2
SUPPORTED_PLUGIN_PROTOCOL_VERSIONS = {1, 2}
CUSTOM_DATA_PLACEHOLDER = {"status": "pending", "message": "自定义数据环境准备中"}
CUSTOM_DATA_COLLECTION_POOL_CORE_WORKERS = 1
CUSTOM_DATA_COLLECTION_POOL_MAX_WORKERS = 5
CUSTOM_DATA_COLLECTION_QUEUE_CAPACITY = 100
CUSTOM_DATA_SLOW_TASK_WARNING_SECONDS = 1.0
CUSTOM_DATA_REMOVE_RETRY_COUNT = 8
CUSTOM_DATA_REMOVE_RETRY_DELAY_SECONDS = 0.25
CUSTOM_DATA_DETAIL_MAX_BYTES = 1024 * 1024
CUSTOM_DATA_PREVIEW_MAX_BYTES = 5 * 1024 * 1024
CUSTOM_DATA_PREVIEW_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
CUSTOM_DATA_ACTION_RESULT_MAX_BYTES = 256 * 1024

TEMPLATE_MANIFEST_CONTENT = '''{
  "protocol": 2,
  "key": "my_data",
  "name": "my_data",
  "zh_name": "我的数据",
  "interval": 5,
  "config_panel": [
    {
      "name": "threshold",
      "zh_name": "阈值",
      "key": "threshold",
      "type": "number",
      "default": 50,
      "min": 0,
      "max": 100,
      "decimal": 0
    }
  ],
  "entry": "main.py",
  "bind_style": false,
  "style": "style_my_data.py",
  "bind_detail": false,
  "detail": "detail.html",
  "bind_preview": false,
  "preview": "preview.png"
}
'''

TEMPLATE_SCRIPT_CONTENT = '''#!/usr/bin/env python3
"""自定义数据插件入口模板。"""

import datetime as dt


def collect(config_json):
    """解析面板配置，采集自定义数据并返回可进行 JSON 序列化的对象。"""
    config = __import__("json").loads(config_json)
    return {
        "time": dt.datetime.now().isoformat(timespec="seconds"),
        "value": config.get("threshold", 0),
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
    config_panel: tuple
    panel_items: tuple
    actions: tuple
    has_uninstall: bool
    bind_style: bool
    modified_time: float
    style_path: Path = None
    detail_path: Path = None
    preview_path: Path = None
    requirements_path: Path = None
    environment_directory: Path = None

    @property
    def panel(self):
        """返回始终包含采集间隔的完整设置面板字段。"""
        interval_field = {
            "name": "interval",
            "zh_name": "采集间隔（秒）",
            "key": "interval",
            "type": "number",
            "default": self.interval,
            "min": 0.1,
            "decimal": 3,
            "required": True,
        }
        return (interval_field,) + self.config_panel

    @property
    def action_map(self):
        """返回动作标识到动作定义的映射副本。"""
        return {action["name"]: dict(action) for action in self.actions}

    @property
    def style_filename(self):
        """返回插件绑定样式的文件名，未绑定时返回空字符串。"""
        return self.style_path.name if self.style_path else ""

    @property
    def detail_filename(self):
        """返回插件绑定简介的文件名，未绑定时返回空字符串。"""
        return self.detail_path.name if self.detail_path else ""

    @property
    def preview_filename(self):
        """返回插件绑定预览图的文件名，未绑定时返回空字符串。"""
        return self.preview_path.name if self.preview_path else ""

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
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "custom_data" / "runner.py"
    return Path(__file__).resolve().parent / "runner.py"


def _validate_identifier(value, field_name):
    """校验插件英文标识并返回原值。"""
    import re

    if not isinstance(value, str) or not value:
        raise CustomDataError("必须定义非空字符串 {}".format(field_name))
    if re.match(CUSTOM_DATA_KEY_PATTERN, value) is None:
        raise CustomDataError("{} 只能包含字母、数字和下划线，且不能以数字开头".format(field_name))
    return value


def _normalize_config_panel(value):
    """校验并标准化插件声明的动态配置面板字段。"""
    if value is None:
        return (), (), set()
    if not isinstance(value, list):
        raise CustomDataError("plugin.json config_panel 必须是数组")
    supported_types = {"string", "number", "boolean", "select", "password", "textarea"}
    normalized = []
    keys = set()
    panel_items = []
    action_names = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            raise CustomDataError("config_panel 第 {} 项必须是对象".format(index))
        kind = str(item.get("kind") or "field").strip().lower()
        if kind == "action":
            action_name = _validate_identifier(item.get("action"), "config_panel.action")
            if action_name in action_names:
                raise CustomDataError("config_panel.action 重复：{}".format(action_name))
            panel_item = {
                "kind": "action",
                "action": action_name,
                "zh_name": str(item.get("zh_name") or action_name).strip(),
                "style": str(item.get("style") or "primary").strip(),
                "confirm": bool(item.get("confirm", False)),
                "loading_text": str(item.get("loading_text") or "正在执行……").strip(),
            }
            if panel_item["style"] not in ("primary", "success", "warning", "danger", "info"):
                raise CustomDataError("config_panel.action {} 的 style 不受支持".format(action_name))
            panel_items.append(panel_item)
            action_names.add(action_name)
            continue
        if kind != "field":
            raise CustomDataError("config_panel 第 {} 项 kind 不受支持".format(index))
        key = _validate_identifier(item.get("key"), "config_panel.key")
        if key == "interval":
            raise CustomDataError("config_panel.key interval 为系统保留字段，无需重复配置")
        if key in keys:
            raise CustomDataError("config_panel.key 重复：{}".format(key))
        field_type = str(item.get("type") or "string").strip().lower()
        if field_type not in supported_types:
            raise CustomDataError("config_panel {} 的 type 不受支持".format(key))
        name = str(item.get("name") or key).strip()
        zh_name = str(item.get("zh_name") or name).strip()
        field = {
            "kind": "field",
            "name": name,
            "zh_name": zh_name,
            "key": key,
            "type": field_type,
            "required": bool(item.get("required", False)),
            "readonly": bool(item.get("readonly", False)),
        }
        for numeric_name in ("min", "max"):
            if item.get(numeric_name) not in (None, ""):
                try:
                    field[numeric_name] = float(item[numeric_name])
                except (TypeError, ValueError) as error:
                    raise CustomDataError("config_panel {} 的 {} 必须是数字".format(key, numeric_name)) from error
        if "min" in field and "max" in field and field["min"] > field["max"]:
            raise CustomDataError("config_panel {} 的 min 不能大于 max".format(key))
        if item.get("decimal") not in (None, ""):
            try:
                decimal = int(item["decimal"])
            except (TypeError, ValueError) as error:
                raise CustomDataError("config_panel {} 的 decimal 必须是非负整数".format(key)) from error
            if decimal < 0 or decimal > 12:
                raise CustomDataError("config_panel {} 的 decimal 必须介于 0 至 12".format(key))
            field["decimal"] = decimal
        if item.get("reg"):
            try:
                import re
                re.compile(str(item["reg"]))
            except re.error as error:
                raise CustomDataError("config_panel {} 的 reg 不是有效正则表达式".format(key)) from error
            field["reg"] = str(item["reg"])
        if field_type == "select":
            options = item.get("options")
            if not isinstance(options, list) or not options:
                raise CustomDataError("config_panel {} 的 select 类型必须定义非空 options".format(key))
            field["options"] = options
        if "default" in item:
            field["default"] = item["default"]
        elif field_type == "number":
            field["default"] = field.get("min", 0)
        elif field_type == "boolean":
            field["default"] = False
        elif field_type == "select":
            first = field["options"][0]
            field["default"] = first.get("value") if isinstance(first, dict) else first
        else:
            field["default"] = ""
        default_field = dict(field)
        default_field["required"] = False
        field["default"] = _normalize_field_value(default_field, field["default"])
        normalized.append(field)
        panel_items.append(field)
        keys.add(key)
    return tuple(normalized), tuple(panel_items), action_names


def _normalize_actions(value, fields, panel_action_names, protocol):
    """校验插件动作白名单，并返回不可变动作定义集合。"""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CustomDataError("plugin.json actions 必须是对象")
    if (value or panel_action_names) and protocol < 2:
        raise CustomDataError("插件动作需要使用 protocol 2")
    field_keys = {field["key"] for field in fields}
    actions = []
    for action_name, item in value.items():
        action_name = _validate_identifier(action_name, "actions.name")
        if not isinstance(item, dict):
            raise CustomDataError("actions.{} 必须是对象".format(action_name))
        method = _validate_identifier(item.get("method", action_name), "actions.method")
        try:
            timeout = float(item.get("timeout", DEFAULT_SCRIPT_TIMEOUT_SECONDS))
        except (TypeError, ValueError) as error:
            raise CustomDataError("actions.{} timeout 必须是数字".format(action_name)) from error
        if not 0.1 <= timeout <= 60:
            raise CustomDataError("actions.{} timeout 必须介于 0.1 至 60 秒".format(action_name))
        patch_keys = item.get("config_keys", [])
        if not isinstance(patch_keys, list):
            raise CustomDataError("actions.{} config_keys 必须是数组".format(action_name))
        normalized_keys = []
        for key in patch_keys:
            key = _validate_identifier(key, "actions.config_keys")
            if key == "interval" or key not in field_keys:
                raise CustomDataError("actions.{} 不允许回填配置项 {}".format(action_name, key))
            if key not in normalized_keys:
                normalized_keys.append(key)
        actions.append(
            {
                "name": action_name,
                "method": method,
                "timeout": timeout,
                "config_keys": normalized_keys,
                "description": str(item.get("description") or "").strip(),
            }
        )
    declared_names = {action["name"] for action in actions}
    missing = panel_action_names - declared_names
    if missing:
        raise CustomDataError("config_panel 引用了未声明动作：{}".format("、".join(sorted(missing))))
    return tuple(actions)


def _load_bound_resource(plugin_path, values, flag_name, field_name, extensions, max_bytes, resource_name):
    """校验清单声明的插件根目录绑定资源并返回完整路径。"""
    enabled = values.get(flag_name, False)
    if not isinstance(enabled, bool):
        raise CustomDataError("plugin.json {} 必须是布尔值".format(flag_name))
    if not enabled:
        return None
    filename = values.get(field_name)
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise CustomDataError("{} 为 true 时 {} 必须是插件根目录内的文件名".format(flag_name, field_name))
    resource_path = Path(plugin_path) / filename
    if resource_path.suffix.lower() not in extensions:
        raise CustomDataError("插件{}文件格式不受支持：{}".format(resource_name, filename))
    if not resource_path.is_file():
        raise CustomDataError("插件{}文件不存在：{}".format(resource_name, filename))
    if resource_path.stat().st_size > max_bytes:
        raise CustomDataError("插件{}文件不能超过 {} MB".format(resource_name, max_bytes // (1024 * 1024)))
    return resource_path


def _validate_preview_content(preview_path):
    """根据文件头校验预览图内容与扩展名相符。"""
    header = preview_path.read_bytes()[:16]
    suffix = preview_path.suffix.lower()
    valid = (
        suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")
        or suffix in (".jpg", ".jpeg") and header.startswith(b"\xff\xd8\xff")
        or suffix == ".gif" and header.startswith((b"GIF87a", b"GIF89a"))
        or suffix == ".webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    )
    if not valid:
        raise CustomDataError("插件预览图内容与文件格式不匹配：{}".format(preview_path.name))


def _normalize_field_value(field, value):
    """按照面板字段定义校验并转换一个配置值。"""
    key = field["key"]
    field_type = field["type"]
    if value is None or value == "":
        if field.get("required"):
            raise CustomDataError("配置项 {} 不能为空".format(field["zh_name"]))
        return "" if field_type not in ("number", "boolean") else field.get("default")
    if field_type == "number":
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise CustomDataError("配置项 {} 必须是数字".format(field["zh_name"])) from error
        if "min" in field and number < field["min"] or "max" in field and number > field["max"]:
            raise CustomDataError("配置项 {} 超出允许范围".format(field["zh_name"]))
        decimal = field.get("decimal")
        if decimal is not None:
            number = round(number, decimal)
        return int(number) if decimal == 0 else number
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if value in (0, 1, "0", "1", "false", "true"):
            return str(value).lower() in ("1", "true")
        raise CustomDataError("配置项 {} 必须是布尔值".format(field["zh_name"]))
    if field_type == "select":
        allowed = {
            option.get("value") if isinstance(option, dict) else option
            for option in field.get("options", ())
        }
        if value not in allowed:
            raise CustomDataError("配置项 {} 的选项无效".format(field["zh_name"]))
        return value
    text = str(value)
    if "min" in field and len(text) < field["min"] or "max" in field and len(text) > field["max"]:
        raise CustomDataError("配置项 {} 的文本长度超出允许范围".format(field["zh_name"]))
    if field.get("reg"):
        import re
        if re.fullmatch(field["reg"], text) is None:
            raise CustomDataError("配置项 {} 的格式无效".format(field["zh_name"]))
    return text


def normalize_plugin_configs(configs, definitions=None, legacy_intervals=None):
    """按当前插件面板生成完整配置，并兼容迁移旧采集频率。"""
    from .manager import get_manager

    definitions = tuple(definitions if definitions is not None else get_manager().list_definitions())
    configs = configs if isinstance(configs, dict) else {}
    legacy_intervals = legacy_intervals if isinstance(legacy_intervals, dict) else {}
    normalized = {}
    for definition in definitions:
        source = configs.get(definition.name)
        source = source if isinstance(source, dict) else {}
        values = {}
        for field in definition.panel:
            default = field.get("default")
            if field["key"] == "interval":
                default = legacy_intervals.get(definition.task_name, default)
            values[field["key"]] = _normalize_field_value(field, source.get(field["key"], default))
        normalized[definition.name] = values
    return normalized


def normalize_plugin_enabled(values, definitions=None, default_enabled=True):
    """按已安装插件生成 Monitor 持久启用状态，忽略未知插件。"""
    from .manager import get_manager

    definitions = tuple(definitions if definitions is not None else get_manager().list_definitions())
    values = values if isinstance(values, dict) else {}
    return {
        definition.name: (
            values.get(definition.name)
            if isinstance(values.get(definition.name), bool)
            else bool(default_enabled)
        )
        for definition in definitions
    }


def normalize_action_config(definition, config):
    """生成动作使用的表单快照，允许尚待动作回填的必填字段为空。"""
    source = config if isinstance(config, dict) else {}
    normalized = {}
    for field in definition.panel:
        relaxed_field = dict(field)
        relaxed_field["required"] = False
        normalized[field["key"]] = _normalize_field_value(
            relaxed_field,
            source.get(field["key"], field.get("default")),
        )
    return normalized


def normalize_action_result(definition, action_name, result):
    """校验插件动作返回值及配置补丁，阻止越权修改 Monitor 配置。"""
    if result is None:
        result = {}
    if not isinstance(result, dict):
        raise CustomDataError("插件动作必须返回 JSON 对象")
    action = definition.action_map.get(action_name)
    if action is None:
        raise CustomDataError("插件未声明动作：{}".format(action_name))
    normalized = {}
    if "message" in result:
        normalized["message"] = str(result["message"])[:1024]
    if "warnings" in result:
        warnings = result["warnings"]
        if not isinstance(warnings, list) or len(warnings) > 20:
            raise CustomDataError("插件动作 warnings 必须是最多 20 项的数组")
        normalized["warnings"] = [str(warning)[:512] for warning in warnings]
    if "data" in result:
        normalized["data"] = result["data"]
    patch = result.get("config_patch", {})
    if not isinstance(patch, dict):
        raise CustomDataError("插件动作 config_patch 必须是对象")
    allowed_keys = set(action["config_keys"])
    unexpected = set(patch) - allowed_keys
    if unexpected:
        raise CustomDataError("插件动作尝试回填未授权配置项：{}".format("、".join(sorted(unexpected))))
    fields = {field["key"]: field for field in definition.config_panel}
    normalized["config_patch"] = {
        key: _normalize_field_value(fields[key], value)
        for key, value in patch.items()
    }
    encoded = json.dumps(normalized, ensure_ascii=False).encode("utf-8")
    if len(encoded) > CUSTOM_DATA_ACTION_RESULT_MAX_BYTES:
        raise CustomDataError("插件动作返回值不能超过 256 KB")
    return normalized


def custom_data_panels():
    """返回 Web 设置页渲染所需的全部自定义插件面板。"""
    from .manager import get_manager

    return [
        {
            "name": definition.name,
            "chineseName": definition.zh_name,
            "fields": [dict(field) for field in definition.panel],
            "items": [
                (
                    dict(item)
                    if item.get("kind") == "action"
                    else dict(item)
                )
                for item in (
                    ({"kind": "field", **definition.panel[0]},)
                    + definition.panel_items
                )
            ],
        }
        for definition in get_manager().list_definitions()
    ]


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
    protocol = values.get("protocol", 1)
    if protocol not in SUPPORTED_PLUGIN_PROTOCOL_VERSIONS:
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
    config_panel, panel_items, panel_action_names = _normalize_config_panel(values.get("config_panel"))
    actions = _normalize_actions(values.get("actions"), config_panel, panel_action_names, protocol)
    has_uninstall = values.get("uninstall", False)
    if not isinstance(has_uninstall, bool):
        raise CustomDataError("plugin.json uninstall 必须是布尔值")
    if has_uninstall and protocol < 2:
        raise CustomDataError("uninstall 清理钩子需要使用 protocol 2")
    bind_style = values.get("bind_style", False)
    if not isinstance(bind_style, bool):
        raise CustomDataError("plugin.json bind_style 必须是布尔值")
    style_path = None
    if bind_style:
        style = values.get("style")
        if not isinstance(style, str) or Path(style).name != style or not style.lower().endswith(".py"):
            raise CustomDataError("bind_style 为 true 时 style 必须是插件根目录内的 py 文件名")
        style_path = plugin_path / style
        if not style_path.is_file():
            raise CustomDataError("插件绑定样式文件不存在：{}".format(style))
    detail_path = _load_bound_resource(
        plugin_path, values, "bind_detail", "detail", {".html", ".htm"},
        CUSTOM_DATA_DETAIL_MAX_BYTES, "简介",
    )
    if detail_path:
        try:
            detail_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise CustomDataError("插件简介必须是 UTF-8 编码的 HTML：{}".format(error)) from error
    preview_path = _load_bound_resource(
        plugin_path, values, "bind_preview", "preview", CUSTOM_DATA_PREVIEW_EXTENSIONS,
        CUSTOM_DATA_PREVIEW_MAX_BYTES, "预览图",
    )
    if preview_path:
        _validate_preview_content(preview_path)
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
        config_panel=config_panel,
        panel_items=panel_items,
        actions=actions,
        has_uninstall=has_uninstall,
        bind_style=bind_style,
        style_path=style_path,
        detail_path=detail_path,
        preview_path=preview_path,
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
