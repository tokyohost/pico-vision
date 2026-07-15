"""验证局域网 WebSocket 服务扫描的网段枚举与协议握手。"""

import base64
import hashlib
import socket
import types
import unittest
from unittest import mock

from net.lan_websocket_discovery import (
    WEBSOCKET_ACCEPT_MAGIC,
    LanWebSocketScanner,
)


class FakeHandshakeSocket:
    """根据客户端随机密钥生成标准 WebSocket 升级响应。"""

    def __init__(self):
        """初始化待发送响应和客户端请求记录。"""
        self.response = b""
        self.request = b""

    def __enter__(self):
        """返回上下文管理器中的模拟套接字。"""
        return self

    def __exit__(self, exception_type, exception, traceback):
        """结束上下文时不屏蔽测试异常。"""
        del exception_type, exception, traceback
        return False

    def settimeout(self, timeout):
        """记录扫描器设置的套接字超时。"""
        self.timeout = timeout

    def sendall(self, request):
        """记录请求，并按其中的密钥构造合法握手响应。"""
        self.request = bytes(request)
        header_text = self.request.decode("ascii")
        key = next(
            line.split(":", 1)[1].strip()
            for line in header_text.split("\r\n")
            if line.lower().startswith("sec-websocket-key:")
        )
        accept = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_ACCEPT_MAGIC).encode("ascii")).digest()
        ).decode("ascii")
        self.response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n"
        ).format(accept).encode("ascii")

    def recv(self, size):
        """一次性返回握手响应。"""
        del size
        response, self.response = self.response, b""
        return response


class LanWebSocketScannerTest(unittest.TestCase):
    """验证扫描器只返回完成标准 WebSocket 握手的地址。"""

    @mock.patch("net.lan_websocket_discovery.socket.create_connection")
    def test_probe_validates_websocket_upgrade(self, create_connection):
        """确认单地址探测发送标准请求并生成可连接 URL。"""
        fake_socket = FakeHandshakeSocket()
        create_connection.return_value = fake_socket
        scanner = LanWebSocketScanner(timeout=0.2)

        result = scanner.probe("192.168.1.20")

        self.assertEqual("ws://192.168.1.20:8765/pv1", result.url)
        self.assertIn(b"GET /pv1 HTTP/1.1", fake_socket.request)
        self.assertIn(b"X-OmniWatch-Discovery: 1", fake_socket.request)
        create_connection.assert_called_once_with(("192.168.1.20", 8765), timeout=0.2)

    @mock.patch("net.lan_websocket_discovery.socket.create_connection")
    def test_port_probe_does_not_send_protocol_data(self, create_connection):
        """端口初筛只建立 TCP 连接，不得向非目标服务发送 WebSocket 数据。"""
        fake_socket = FakeHandshakeSocket()
        create_connection.return_value = fake_socket
        scanner = LanWebSocketScanner(timeout=0.15)

        self.assertTrue(scanner.port_is_open_safely("192.168.1.20"))

        self.assertEqual(b"", fake_socket.request)
        create_connection.assert_called_once_with(("192.168.1.20", 8765), timeout=0.15)

    @mock.patch("net.lan_websocket_discovery._load_psutil")
    def test_local_hosts_merge_active_networks(self, load_psutil):
        """确认启用网卡的网段会合并去重，并排除本机与回环地址。"""
        net_if_stats = mock.Mock(return_value={
            "以太网": types.SimpleNamespace(isup=True),
            "停用网卡": types.SimpleNamespace(isup=False),
        })
        net_if_addrs = mock.Mock(return_value={
            "以太网": [
                types.SimpleNamespace(
                    family=socket.AF_INET,
                    address="192.168.8.2",
                    netmask="255.255.255.252",
                )
            ],
            "停用网卡": [
                types.SimpleNamespace(
                    family=socket.AF_INET,
                    address="10.0.0.2",
                    netmask="255.255.255.0",
                )
            ],
        })
        load_psutil.return_value = types.SimpleNamespace(
            net_if_stats=net_if_stats,
            net_if_addrs=net_if_addrs,
        )

        self.assertEqual(("192.168.8.1",), LanWebSocketScanner.local_hosts())

    @mock.patch("net.lan_websocket_discovery._load_psutil")
    def test_large_network_is_limited_to_local_24_prefix(self, load_psutil):
        """确认大网段只快速探测本机所在二十四位子网，避免周期扫描冲击局域网。"""
        load_psutil.return_value = types.SimpleNamespace(
            net_if_stats=mock.Mock(return_value={"以太网": types.SimpleNamespace(isup=True)}),
            net_if_addrs=mock.Mock(return_value={
                "以太网": [types.SimpleNamespace(
                    family=socket.AF_INET,
                    address="10.20.30.40",
                    netmask="255.255.0.0",
                )],
            }),
        )

        networks = LanWebSocketScanner.local_networks()

        self.assertEqual(("10.20.30.0/24",), tuple(str(network) for network in networks))
        self.assertEqual(253, len(LanWebSocketScanner.local_hosts()))

    def test_scan_uses_multiple_workers_and_keeps_only_successes(self):
        """确认批量扫描只对端口开放地址执行 WebSocket 协议握手。"""
        scanner = LanWebSocketScanner(max_workers=8)
        scanner.port_is_open = mock.Mock(side_effect=lambda ip: ip.endswith("2"))
        scanner.probe = mock.Mock(side_effect=lambda ip: (
            types.SimpleNamespace(ip=ip)
            if ip.endswith("2")
            else (_ for _ in ()).throw(OSError("拒绝连接"))
        ))

        results = scanner.scan(hosts=("192.168.1.1", "192.168.1.2"))

        self.assertEqual(["192.168.1.2"], [result.ip for result in results])
        scanner.probe.assert_called_once_with("192.168.1.2")


if __name__ == "__main__":
    unittest.main()
