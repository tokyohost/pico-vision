"""实现 USB 优先的多传输选择、抢占以及断线恢复。"""

from net.usb_cdc import UsbCdcTransport


class TransportManager:
    """统一管理 USB CDC 与 Wi-Fi WebSocket，并始终优先使用 USB。"""

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
        self._usb_transport = None
        self._wifi_transport = None
        self._strategies = []
        if usb_stream is not None:
            self._usb_transport = UsbCdcTransport(usb_stream)
            self._strategies.append(self._usb_transport)
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
        """优先选择 USB；USB 断开后才推进并选择 WebSocket。"""
        if self._usb_transport is not None:
            self._usb_transport.update()
            if self._usb_transport.is_connected():
                if self._active is not self._usb_transport:
                    # USB 建立连接后立即关闭 WebSocket 会话，避免两个通道
                    # 同时收发 PV1 数据；USB 断开后会重新启动监听。
                    if self._wifi_transport is not None:
                        self._wifi_transport.close()
                    self._active = self._usb_transport
                return

        if self._active is not None and not self._active.is_connected():
            self._active = None

        # USB 未连接时才推进 Wi-Fi WebSocket，确保 USB 会话期间完全忽略它。
        if self._wifi_transport is not None:
            self._wifi_transport.update()

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

    def websocket_transport(self):
        """返回 WebSocket 管理服务，供设备命令查询和修改客户端策略。"""
        return self._wifi_transport

    def close(self):
        """关闭全部候选传输策略。"""
        for strategy in self._strategies:
            strategy.close()
        self._active = None
