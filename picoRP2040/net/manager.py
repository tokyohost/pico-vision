"""实现多传输策略竞选、锁定以及断线释放。"""

from net.usb_cdc import UsbCdcTransport


class TransportManager:
    """在 USB CDC 与 Wi-Fi WebSocket 中锁定首个可用连接。"""

    def __init__(
        self,
        usb_stream=None,
        wifi_enabled=True,
        websocket_port=8765,
        websocket_path="/pv1",
    ):
        """根据开关创建 USB 和可选 Wi-Fi 候选传输策略。"""
        self.wifi_enabled = bool(wifi_enabled)
        self.wifi = None
        self._wifi_transport = None
        self._strategies = []
        if usb_stream is not None:
            self._strategies.append(UsbCdcTransport(usb_stream))
        if self.wifi_enabled:
            from net.websocket import WebSocketTransport
            from net.wifi import WifiManager

            self.wifi = WifiManager()
            self._wifi_transport = WebSocketTransport(
                self.wifi,
                port=websocket_port,
                path=websocket_path,
            )
            self._strategies.append(self._wifi_transport)
        self._active = None

    def _update_selection(self):
        """推进全部候选，并在活动连接断开后重新选择首个连接。"""
        for strategy in self._strategies:
            strategy.update()
        if self._active is not None and not self._active.is_connected():
            self._active = None
        if self._active is None:
            for strategy in self._strategies:
                if strategy.is_connected():
                    self._active = strategy
                    break

    def available(self):
        """返回活动策略当前可读取的字节数。"""
        self._update_selection()
        return self._active.available() if self._active is not None else 0

    def readinto(self, buffer):
        """从已锁定策略读取数据。"""
        self._update_selection()
        return self._active.readinto(buffer) if self._active is not None else 0

    def write(self, data):
        """仅通过已锁定策略发送数据，防止跨通道响应串线。"""
        self._update_selection()
        if self._active is None:
            return 0
        written = self._active.write(data)
        if not self._active.is_connected():
            self._active = None
        return written

    def flush(self):
        """刷新当前活动策略的发送缓冲。"""
        return self._active.flush() if self._active is not None else None

    def is_open(self):
        """返回是否存在已经锁定的活动传输。"""
        self._update_selection()
        return self._active is not None and self._active.is_connected()

    def active_mode(self):
        """返回当前锁定模式，尚未连接时返回 none。"""
        self._update_selection()
        return self._active.name if self._active is not None else "none"

    def preferred_write_size(self):
        """返回活动策略适合的单次写入大小。"""
        return 65535 if self.active_mode() == "wifi" else 63

    def status(self):
        """返回当前模式；Wi-Fi 模式额外返回无线网络详情。"""
        self._update_selection()
        if self._active is not None:
            details = self._active.status()
            details["wifi_enabled"] = self.wifi_enabled
            return details
        return {
            "mode": "none",
            "connected": False,
            "wifi_enabled": self.wifi_enabled,
        }

    def wifi_status(self):
        """返回供系统启动页固定展示的 Wi-Fi 与 WebSocket 状态。"""
        if not self.wifi_enabled or self.wifi is None:
            return {"enabled": False}
        details = self.wifi.status()
        details["enabled"] = True
        if self._wifi_transport is not None:
            transport_status = self._wifi_transport.status()
            details.update({
                "websocket_connected": transport_status.get("connected", False),
                "websocket_port": transport_status.get("websocket_port"),
                "websocket_path": transport_status.get("websocket_path"),
                "peer": transport_status.get("peer"),
            })
        return details

    def close(self):
        """关闭全部候选传输策略。"""
        for strategy in self._strategies:
            strategy.close()
        self._active = None
