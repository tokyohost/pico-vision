"""采集设备只读信息，单项失败不影响其他信息展示。"""

import gc
import config
from device_identity import device_uuid
from protocol import runtime_sdk_version
from i18n import t


def _read(provider):
    """隔离设备接口异常，以未知值保留对应字段。"""
    try:
        value = provider()
        return str(value) if value is not None and value != "" else t("info.unknown")
    except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        return t("info.unavailable")


def _row(key, value):
    """生成稳定标识、翻译标签与完整值组成的信息项。"""
    return (key, t("info." + key), value)


def static_information(lcd):
    """读取每次进入系统信息时需要更新的静态设备资料。"""
    return [
        _row("sdk", _read(runtime_sdk_version)),
        _row("firmware", _read(lambda: config.FIRMWARE_VERSION)),
        _row("device_id", _read(device_uuid)),
        _row("device_name", _read(lambda: config.DEVICE_NAME)),
        _row("board", _read(lambda: config.BOARD_MODEL)),
        _row("screen", _read(lambda: config.LCD_DEVICE_TYPE)),
        _row("resolution", _read(lambda: "{} × {}".format(
            lcd.panel_profile.width, lcd.panel_profile.height))),
    ]


def _memory():
    """读取堆统计，不触发垃圾回收或额外内存探测。"""
    used, free = gc.mem_alloc(), gc.mem_free()
    total = used + free
    percent = used * 100 / total if total else 0
    return t("info.memory_value", {"used": used, "free": free,
                                   "total": total, "percent": "{:.1f}".format(percent)})


def _status(transport, method):
    """读取已有连接状态，不发起连接或无线扫描。"""
    if transport is None:
        return {}
    try:
        value = getattr(transport, method)()
        return value if isinstance(value, dict) else None
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None


def dynamic_information(transport):
    """采样内存、当前传输与无线网络运行状态。"""
    link = _status(transport, "status")
    wifi = _status(transport, "wifi_status")
    unavailable = t("info.unavailable")
    if link is None:
        connection = unavailable
    elif not link.get("connected"):
        connection = t("info.disconnected")
    else:
        mode = link.get("mode", "")
        name = {"usb": "USB", "websocket": "Wi-Fi", "wifi": "Wi-Fi"}.get(mode, mode or t("info.unknown"))
        connection = name + " / " + t("info.connected")
    if wifi is None:
        state = ssid = ip = unavailable
    else:
        enabled = wifi.get("enabled", False)
        connected = bool(enabled and wifi.get("connected"))
        state = t("info.disabled") if not enabled else (
            unavailable if not wifi.get("available", True) else
            t("info.connected") if connected else t("info.disconnected"))
        ssid = str(wifi.get("ssid") or t("info.unknown")) if enabled else t("info.disabled")
        ip = str(wifi.get("ip") or t("info.unknown")) if connected else t("info.disconnected")
    return [_row("memory", _read(_memory)), _row("connection", connection),
            _row("wifi", state), _row("ssid", ssid), _row("ip", ip)]


def about_information():
    """返回与电脑端关于页面一致的项目介绍。"""
    return [_row("product", "OmniWatch"), _row("description", t("info.description_value")),
            _row("author", "tokyohost"),
            _row("project", "https://github.com/tokyohost/omniwatch-doc")]
