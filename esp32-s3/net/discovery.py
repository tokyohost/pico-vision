"""通过 UDP 组播和广播主动公告 ESP32 WebSocket 服务。"""

import time

try:
    import ujson as json
except ImportError:
    import json


DISCOVERY_MAGIC = "FN_VISION_DISCOVERY"
DISCOVERY_VERSION = 1


class UdpDiscoveryAnnouncer:
    """在 Wi-Fi 联网期间周期发送轻量设备发现公告。"""

    def __init__(
        self,
        wifi,
        websocket_port,
        websocket_path,
        device_id="",
        board_model="ESP32-S3",
        discovery_port=37856,
        multicast_group="239.255.77.77",
        interval_ms=2000,
    ):
        """保存网络服务信息，套接字延迟到首次联网时创建。"""
        self._wifi = wifi
        self._websocket_port = int(websocket_port)
        self._websocket_path = "/" + str(websocket_path or "").lstrip("/")
        self._device_id = str(device_id or "")
        self._board_model = str(board_model or "ESP32-S3")
        self._discovery_port = int(discovery_port)
        self._multicast_group = str(multicast_group)
        self._interval_ms = max(250, int(interval_ms))
        self._socket = None
        self._next_announcement_ms = 0

    @staticmethod
    def _ticks_ms():
        """返回兼容 MicroPython 与 CPython 测试环境的毫秒时钟。"""
        ticks_ms = getattr(time, "ticks_ms", None)
        return ticks_ms() if ticks_ms else int(time.monotonic() * 1000)

    @staticmethod
    def _due(now, deadline):
        """使用可回绕时钟判断公告截止时间。"""
        ticks_diff = getattr(time, "ticks_diff", None)
        return ticks_diff(now, deadline) >= 0 if ticks_diff else now >= deadline

    @staticmethod
    def _add_ticks(value, delta):
        """使用可回绕时钟计算下一次公告时间。"""
        ticks_add = getattr(time, "ticks_add", None)
        return ticks_add(value, int(delta)) if ticks_add else value + int(delta)

    def _open_socket(self):
        """创建允许发送广播的 UDP 套接字。"""
        import socket

        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except (AttributeError, OSError):
            # 精简固件可能缺少广播套接字常量，仍保留组播公告能力。
            pass
        self._socket = connection

    def _payload(self):
        """生成稳定、可扩展且不包含 Wi-Fi 凭据的公告 JSON。"""
        status = self._wifi.status()
        return json.dumps({
            "magic": DISCOVERY_MAGIC,
            "version": DISCOVERY_VERSION,
            "board_model": self._board_model,
            "device_id": self._device_id,
            "ip": status.get("ip"),
            "websocket_port": self._websocket_port,
            "websocket_path": self._websocket_path,
        }).encode("utf-8")

    def update(self):
        """到达周期且 Wi-Fi 已联网时发送一次组播和广播公告。"""
        if self._wifi is None or not self._wifi.is_connected():
            self.close()
            self._next_announcement_ms = 0
            return False
        now = self._ticks_ms()
        if not self._due(now, self._next_announcement_ms):
            return False
        self._next_announcement_ms = self._add_ticks(now, self._interval_ms)
        try:
            if self._socket is None:
                self._open_socket()
            payload = self._payload()
            sent = False
            # 组播适合多网卡环境，受限路由器不转发组播时由广播提供兼容路径。
            for target in (
                (self._multicast_group, self._discovery_port),
                ("255.255.255.255", self._discovery_port),
            ):
                try:
                    self._socket.sendto(payload, target)
                    sent = True
                except OSError:
                    continue
            if sent:
                return True
            self.close()
            return False
        except (AttributeError, OSError):
            self.close()
            return False

    def close(self):
        """关闭公告套接字；后续重新联网时会自动重建。"""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        self._socket = None
