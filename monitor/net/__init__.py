"""提供 Monitor 端可复用的网络发现与传输策略。"""

from net.lan_websocket_discovery import LanWebSocketScanner, WebSocketProbeResult

__all__ = ("LanWebSocketScanner", "WebSocketDevice", "WebSocketProbeResult")


def __getattr__(name):
    """按需加载 WebSocket 传输适配器，保持网络扫描模块可独立复用。"""
    if name != "WebSocketDevice":
        raise AttributeError(name)
    from net.websocket_transport import WebSocketDevice

    return WebSocketDevice
