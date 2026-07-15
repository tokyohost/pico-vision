"""Windows 托盘配置模型、持久化与启动参数转换。"""

import json
from pathlib import Path

from custom_data import custom_data_task_defaults, custom_data_task_zh_names
from collectTask import system_task_defaults, system_task_zh_names
from collectTask.system_tasks import system_task_aliases


STYLE_NAMES = {
    "default": "经典概览",
    "disk": "磁盘概览",
    "diskv2": "十五盘紧凑版",
    "diskv3": "十五盘 IP 版",
    "diskv4": "十五盘趋势版",
    "horizontal_disk": "九盘横屏版",
    "horizontal_diskv2": "九盘紧凑版",
    "horizontal_disk4x": "四盘清晰版",
    "horizontal_disk4x_qb": "四盘下载版(qBittorrent)",
    "horizontal_disk6x": "六盘均衡版",
    "simple": "三盘简洁版",
    "fps_simple": "FPS 监控简约",
    "game": "游戏监控简约",
}
DEFAULT_STYLE_CATALOG = [
    {"name": name, "chinese_name": chinese_name, "type": "builtin"}
    for name, chinese_name in STYLE_NAMES.items()
]
DEFAULT_COLLECTION_TASK_INTERVALS = system_task_defaults()
DEFAULT_COLLECTION_TASK_INTERVALS.update(custom_data_task_defaults())
COLLECTION_TASK_ZH_NAMES = system_task_zh_names()
COLLECTION_TASK_ZH_NAMES.update(custom_data_task_zh_names())
DEFAULT_SETTINGS = {
    "port": "",
    "websocket_url": "",
    "ping_target": "www.baidu.com",
    "interval": 0.5,
    "adaptive_transmit": True,
    "reconnect_interval": 3.0,
    "serial_probe_interval": 3.0,
    "lan_probe_port": 8765,
    "lan_probe_path": "/pv1",
    "lan_probe_timeout": 0.3,
    "lan_probe_max_workers": 256,
    "collection_task_intervals": dict(DEFAULT_COLLECTION_TASK_INTERVALS),
    "collection_task_logs": True,
    "screen_rotation": 0,
    "lcd_brightness": 100,
    "network_unit": "MB",
    "lcd_style": "horizontal_disk6x",
    "styles": DEFAULT_STYLE_CATALOG,
    "dev": False,
    "qbittorrent_enabled": False,
    "qbittorrent_address": "",
    "qbittorrent_username": "",
    "qbittorrent_password": "",
    "qbittorrent_interval": 2.0,
    "update_url": "",
}
ARGUMENT_NAMES = {
    "--port": "port",
    "--websocket-url": "websocket_url",
    "--ping-target": "ping_target",
    "--interval": "interval",
    "--reconnect-interval": "reconnect_interval",
    "--serial-probe-interval": "serial_probe_interval",
    "--lan-probe-port": "lan_probe_port",
    "--lan-probe-path": "lan_probe_path",
    "--lan-probe-timeout": "lan_probe_timeout",
    "--lan-probe-max-workers": "lan_probe_max_workers",
    "--collection-task-intervals": "collection_task_intervals",
    "--screen-rotation": "screen_rotation",
    "--lcd-brightness": "lcd_brightness",
    "--network-unit": "network_unit",
    "--lcd-style": "lcd_style",
    "--qbittorrent-address": "qbittorrent_address",
    "--qbittorrent-username": "qbittorrent_username",
    "--qbittorrent-password": "qbittorrent_password",
    "--qbittorrent-interval": "qbittorrent_interval",
}


def style_names(settings=None):
    """从配置中的样式清单构建名称到中文名称的映射。"""
    catalog = (settings or {}).get("styles", DEFAULT_STYLE_CATALOG)
    return {
        item["name"]: item["chinese_name"]
        for item in catalog
        if isinstance(item, dict) and item.get("name") and item.get("chinese_name")
    } or dict(STYLE_NAMES)


def style_label(style, settings=None):
    """返回包含中文名称和程序名称的样式显示文本。"""
    names = style_names(settings)
    return "{}（{}）".format(names.get(style, style), style)


def normalize_style_catalog(catalog):
    """校验设备样式清单，并在保留全部内置样式的基础上合并自定义样式。"""
    normalized = [dict(item) for item in DEFAULT_STYLE_CATALOG]
    seen = {item["name"] for item in normalized}
    for item in catalog if isinstance(catalog, list) else ():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        chinese_name = str(item.get("chinese_name") or "").strip()
        style_type = item.get("type")
        if not name or not chinese_name or name in seen or style_type not in ("builtin", "custom"):
            continue
        normalized.append({"name": name, "chinese_name": chinese_name, "type": style_type})
        seen.add(name)
    return normalized


def normalize_collection_task_intervals(intervals):
    """校验系统采集任务频率配置，并补齐新增任务的默认频率。"""
    normalized = dict(DEFAULT_COLLECTION_TASK_INTERVALS)
    aliases = system_task_aliases()
    if not isinstance(intervals, dict):
        return normalized
    for name, interval in intervals.items():
        name = aliases.get(name, name)
        if name not in normalized:
            continue
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            continue
        if interval > 0:
            normalized[name] = interval
    return normalized

class TraySettingsStore:
    """在当前用户目录持久化托盘配置。"""

    def __init__(self, path):
        """绑定一个 JSON 配置文件路径。"""
        self.path = Path(path)

    def load(self):
        """读取托盘 JSON 配置，并对缺失或无效字段执行默认值修复。"""
        settings = dict(DEFAULT_SETTINGS)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                settings.update({key: payload[key] for key in settings if key in payload})
        except (OSError, ValueError, TypeError):
            pass
        settings["styles"] = normalize_style_catalog(settings.get("styles")) or list(DEFAULT_STYLE_CATALOG)
        settings["collection_task_intervals"] = normalize_collection_task_intervals(settings.get("collection_task_intervals"))
        if settings["lcd_style"] not in style_names(settings):
            settings["lcd_style"] = DEFAULT_SETTINGS["lcd_style"]
        try:
            settings["lcd_brightness"] = int(settings["lcd_brightness"])
        except (TypeError, ValueError):
            settings["lcd_brightness"] = DEFAULT_SETTINGS["lcd_brightness"]
        if not 1 <= settings["lcd_brightness"] <= 100:
            settings["lcd_brightness"] = DEFAULT_SETTINGS["lcd_brightness"]
        settings["adaptive_transmit"] = bool(settings.get("adaptive_transmit", True))
        settings["collection_task_logs"] = bool(settings.get("collection_task_logs", True))
        try:
            settings["lan_probe_port"] = int(settings["lan_probe_port"])
            if not 1 <= settings["lan_probe_port"] <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            settings["lan_probe_port"] = DEFAULT_SETTINGS["lan_probe_port"]
        lan_probe_path = str(settings.get("lan_probe_path") or "").strip()
        settings["lan_probe_path"] = (
            "/" + lan_probe_path.lstrip("/")
            if lan_probe_path
            else DEFAULT_SETTINGS["lan_probe_path"]
        )
        try:
            settings["lan_probe_timeout"] = float(settings["lan_probe_timeout"])
            if settings["lan_probe_timeout"] <= 0:
                raise ValueError
        except (TypeError, ValueError):
            settings["lan_probe_timeout"] = DEFAULT_SETTINGS["lan_probe_timeout"]
        try:
            settings["lan_probe_max_workers"] = int(settings["lan_probe_max_workers"])
            if settings["lan_probe_max_workers"] <= 0:
                raise ValueError
        except (TypeError, ValueError):
            settings["lan_probe_max_workers"] = DEFAULT_SETTINGS["lan_probe_max_workers"]
        return settings

    def save(self, settings):
        """以无 BOM 的 UTF-8 JSON 原子保存配置。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def apply_worker_arguments(arguments, settings):
    """保留非界面参数，并用托盘配置覆盖受管理的启动参数。"""
    retained = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in ARGUMENT_NAMES:
            index += 2
            continue
        if argument in (
                "--dev", "--no-dev", "--qbittorrent-enabled", "--no-qbittorrent",
                "--adaptive-transmit", "--no-adaptive-transmit",
                "--collection-task-logs", "--no-collection-task-logs",
        ):
            index += 1
            continue
        retained.append(argument)
        index += 1
    for option, name in ARGUMENT_NAMES.items():
        value = settings[name]
        if name in (
            "port", "websocket_url", "qbittorrent_address",
            "qbittorrent_username", "qbittorrent_password",
        ) and not value:
            continue
        if name == "collection_task_intervals":
            value = json.dumps(normalize_collection_task_intervals(value), ensure_ascii=False)
        retained.extend((option, str(value)))
    retained.append("--qbittorrent-enabled" if settings["qbittorrent_enabled"] else "--no-qbittorrent")
    retained.append("--adaptive-transmit" if settings["adaptive_transmit"] else "--no-adaptive-transmit")
    retained.append("--collection-task-logs" if settings["collection_task_logs"] else "--no-collection-task-logs")
    if settings["dev"]:
        retained.append("--dev")
    return retained


def settings_from_arguments(arguments, base=None):
    """从已有启动参数提取配置，用于首次升级时平滑迁移。"""
    settings = dict(DEFAULT_SETTINGS if base is None else base)
    converters = {
        "interval": float, "reconnect_interval": float, "serial_probe_interval": float,
        "lan_probe_port": int, "lan_probe_timeout": float, "lan_probe_max_workers": int,
        "screen_rotation": int, "lcd_brightness": int,
        "qbittorrent_interval": float,
        "collection_task_intervals": lambda value: normalize_collection_task_intervals(json.loads(value)),
    }
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in ARGUMENT_NAMES and index + 1 < len(arguments):
            name = ARGUMENT_NAMES[argument]
            try:
                settings[name] = converters.get(name, str)(arguments[index + 1])
            except (TypeError, ValueError):
                pass
            index += 2
            continue
        if argument == "--qbittorrent-enabled":
            settings["qbittorrent_enabled"] = True
        elif argument == "--no-qbittorrent":
            settings["qbittorrent_enabled"] = False
        elif argument == "--adaptive-transmit":
            settings["adaptive_transmit"] = True
        elif argument == "--no-adaptive-transmit":
            settings["adaptive_transmit"] = False
        elif argument == "--collection-task-logs":
            settings["collection_task_logs"] = True
        elif argument == "--no-collection-task-logs":
            settings["collection_task_logs"] = False
        elif argument == "--dev":
            settings["dev"] = True
        elif argument == "--no-dev":
            settings["dev"] = False
        index += 1
    settings["collection_task_intervals"] = normalize_collection_task_intervals(settings.get("collection_task_intervals"))
    return settings
