"""Windows 托盘配置模型、持久化与启动参数转换。"""

import json
from pathlib import Path


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
}
DEFAULT_SETTINGS = {
    "port": "",
    "ping_target": "www.baidu.com",
    "interval": 0.5,
    "reconnect_interval": 3.0,
    "screen_rotation": 0,
    "network_unit": "MB",
    "lcd_style": "horizontal_disk6x",
    "qbittorrent_enabled": False,
    "qbittorrent_address": "",
    "qbittorrent_username": "",
    "qbittorrent_password": "",
    "qbittorrent_interval": 2.0,
}
ARGUMENT_NAMES = {
    "--port": "port",
    "--ping-target": "ping_target",
    "--interval": "interval",
    "--reconnect-interval": "reconnect_interval",
    "--screen-rotation": "screen_rotation",
    "--network-unit": "network_unit",
    "--lcd-style": "lcd_style",
    "--qbittorrent-address": "qbittorrent_address",
    "--qbittorrent-username": "qbittorrent_username",
    "--qbittorrent-password": "qbittorrent_password",
    "--qbittorrent-interval": "qbittorrent_interval",
}


def style_label(style):
    return "{}（{}）".format(STYLE_NAMES.get(style, style), style)


class TraySettingsStore:
    """在当前用户目录持久化托盘配置。"""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                settings.update({key: payload[key] for key in settings if key in payload})
        except (OSError, ValueError, TypeError):
            pass
        if settings["lcd_style"] not in STYLE_NAMES:
            settings["lcd_style"] = DEFAULT_SETTINGS["lcd_style"]
        return settings

    def save(self, settings):
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
        if argument in ("--qbittorrent-enabled", "--no-qbittorrent"):
            index += 1
            continue
        retained.append(argument)
        index += 1
    for option, name in ARGUMENT_NAMES.items():
        value = settings[name]
        if name in ("port", "qbittorrent_address", "qbittorrent_username", "qbittorrent_password") and not value:
            continue
        retained.extend((option, str(value)))
    retained.append("--qbittorrent-enabled" if settings["qbittorrent_enabled"] else "--no-qbittorrent")
    return retained


def settings_from_arguments(arguments, base=None):
    """从已有启动参数提取配置，用于首次升级时平滑迁移。"""
    settings = dict(DEFAULT_SETTINGS if base is None else base)
    converters = {
        "interval": float, "reconnect_interval": float,
        "screen_rotation": int, "qbittorrent_interval": float,
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
        index += 1
    return settings
