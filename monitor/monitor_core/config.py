"""监控程序配置读取与转换工具。"""

import argparse
import json
import os
import shlex
from pathlib import Path

from collectTask import system_task_defaults
from collectTask.system_tasks import system_task_aliases
from custom_data import custom_data_task_defaults

CONFIG_ENV_MAP = {
    "PICO_MONITOR_PORT": ("serial", "port"),
    "PICO_MONITOR_WEBSOCKET_URL": ("network", "websocket_url"),
    "PICO_MONITOR_PING_TARGET": ("network", "ping_target"),
    "PICO_MONITOR_INTERVAL": ("monitor", "interval"),
    "PICO_MONITOR_ADAPTIVE_TRANSMIT": ("monitor", "adaptive_transmit"),
    "PICO_MONITOR_COLLECTION_TASK_INTERVALS": ("collection_tasks", "intervals"),
    "PICO_MONITOR_RECONNECT_INTERVAL": ("monitor", "reconnect_interval"),
    "PICO_MONITOR_SERIAL_PROBE_INTERVAL": ("serial", "probe_interval"),
    "PICO_MONITOR_SCREEN_ROTATION": ("screen", "rotation"),
    "PICO_MONITOR_LCD_BRIGHTNESS": ("screen", "lcd_brightness"),
    "PICO_MONITOR_NETWORK_UNIT": ("network", "unit"),
    "PICO_MONITOR_LCD_STYLE": ("screen", "lcd_style"),
    "PICO_MONITOR_DEV": ("monitor", "dev"),
    "PICO_MONITOR_LOG_LEVEL": ("logging", "level"),
    "PICO_MONITOR_THREAD_DIAGNOSTICS": ("diagnostics", "threads"),
    "PICO_MONITOR_THREAD_DIAGNOSTICS_INTERVAL": ("diagnostics", "thread_interval"),
    "PICO_MONITOR_SENSOR_HOST_ENABLED": ("sensor_host", "enabled"),
    "PICO_MONITOR_SENSOR_HOST_PATH": ("sensor_host", "path"),
    "PICO_MONITOR_SENSOR_HOST_PIPE": ("sensor_host", "pipe"),
    "PICO_MONITOR_QBITTORRENT_ENABLED": ("qbittorrent", "enabled"),
    "PICO_MONITOR_QBITTORRENT_ADDRESS": ("qbittorrent", "address"),
    "PICO_MONITOR_QBITTORRENT_USERNAME": ("qbittorrent", "username"),
    "PICO_MONITOR_QBITTORRENT_PASSWORD": ("qbittorrent", "password"),
    "PICO_MONITOR_QBITTORRENT_INTERVAL": ("qbittorrent", "interval"),
    "PICO_MONITOR_DISK_HEALTH_TEST_INDEX": ("disk_health_test", "index"),
    "PICO_MONITOR_DISK_HEALTH_TEST_LEVEL": ("disk_health_test", "level"),
    "PICO_MONITOR_UPGRADE_URL": ("upgrade", "url"),
    "PICO_MONITOR_UPGRADE_SHA256": ("upgrade", "sha256"),
}

def environment_flag(name, default=False):
    """读取常见布尔环境变量值，无法识别时使用默认值。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _parse_legacy_environment_config(text):
    """解析旧版 EnvironmentFile 配置，兼容已安装用户的原有文件。"""
    config = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        name = name.strip()
        if not name.startswith("PICO_MONITOR_"):
            continue
        try:
            parts = shlex.split(raw_value, comments=False, posix=True)
        except ValueError:
            parts = [raw_value.strip().strip("\"'")]
        config[name] = parts[0] if parts else ""
    return config


def load_monitor_config(config_path):
    """读取 YAML 配置文件，并在必要时兼容旧版环境变量格式。"""
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    first_content_line = next(
        (line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")),
        "",
    )
    if first_content_line.startswith("PICO_MONITOR_"):
        return _parse_legacy_environment_config(text)
    try:
        import yaml
    except ImportError as error:
        raise SystemExit("读取 YAML 配置需要安装 PyYAML 依赖") from error
    try:
        payload = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        raise SystemExit("YAML 配置解析失败：{}".format(error)) from error
    if not isinstance(payload, dict):
        raise SystemExit("YAML 配置根节点必须是对象")
    return payload


def _nested_config_value(config, path, missing=None):
    """按层级路径读取 YAML 配置值，缺失时返回指定默认值。"""
    current = config
    for name in path:
        if not isinstance(current, dict) or name not in current:
            return missing
        current = current[name]
    return current


def config_value(config, environment_name, default=None):
    """按优先级读取配置：环境变量优先，其次 YAML/旧配置文件，最后默认值。"""
    value = os.getenv(environment_name)
    if value is not None:
        return value
    if not config:
        return default
    if environment_name in config:
        return config[environment_name]
    path = CONFIG_ENV_MAP.get(environment_name)
    if path is None:
        return default
    return _nested_config_value(config, path, default)


def config_flag(config, environment_name, default=False):
    """读取布尔配置值，支持 YAML 布尔和旧环境变量字符串。"""
    value = config_value(config, environment_name, None)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def parse_collection_task_intervals(value):
    """解析任务采集频率配置，并只保留已发现任务的正数频率。"""
    defaults = system_task_defaults()
    defaults.update(custom_data_task_defaults())
    aliases = system_task_aliases()
    if not value:
        return dict(defaults)
    if isinstance(value, dict):
        payload = value
    else:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise argparse.ArgumentTypeError("采集任务频率必须是 JSON 对象") from error
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("采集任务频率必须是 JSON 对象")
    intervals = dict(defaults)
    for name, interval in payload.items():
        name = aliases.get(name, name)
        if name not in defaults:
            continue
        try:
            interval = float(interval)
        except (TypeError, ValueError) as error:
            raise argparse.ArgumentTypeError("{} 的采集频率必须是数字".format(name)) from error
        if interval <= 0:
            raise argparse.ArgumentTypeError("{} 的采集频率必须大于 0".format(name))
        intervals[name] = interval
    return intervals
