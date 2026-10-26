"""跨平台设备展示与传输类型转换。"""

from i18n import t


def format_connection_method(connection):
    """将设备传输标识转换为面向用户的标准连接方式名称。"""
    transport = str((connection or {}).get("transport") or "").strip()
    normalized = transport.lower().replace("_", " ").replace("-", " ")
    if normalized in (t('ui.serial_port'), "serial", "usb", "usb cdc"):
        return t('message.usb_cdc_serial')
    if normalized in ("websocket", "wifi", "wi fi"):
        return "Wi-Fi（WebSocket）"
    return transport or t('ui.unknown')
