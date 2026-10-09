"""跨平台设备展示与传输类型转换。"""


def format_connection_method(connection):
    """将设备传输标识转换为面向用户的标准连接方式名称。"""
    transport = str((connection or {}).get("transport") or "").strip()
    normalized = transport.lower().replace("_", " ").replace("-", " ")
    if normalized in ("串口", "serial", "usb", "usb cdc"):
        return "USB CDC（串口）"
    if normalized in ("websocket", "wifi", "wi fi"):
        return "Wi-Fi（WebSocket）"
    return transport or "未知"
