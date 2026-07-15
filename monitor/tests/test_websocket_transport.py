"""验证 Monitor WebSocket 传输适配器的分帧、心跳和关闭行为。"""

import sys
import types
import unittest
from unittest import mock

import serial

from net.websocket_transport import WebSocketDevice


class FakeWebSocketException(Exception):
    """模拟 websocket-client 的通用协议异常。"""


class FakeWebSocketTimeout(FakeWebSocketException):
    """模拟 websocket-client 的接收超时异常。"""


class FakeWebSocket:
    """记录二进制消息和心跳的内存 WebSocket。"""

    def __init__(self):
        """初始化连接状态、收发记录和预置输入消息。"""
        self.connected = True
        self.sent = []
        self.pings = []
        self.incoming = [b"PV1:PONG:0:0000:\n"]

    def settimeout(self, timeout):
        """记录适配器设置的读取超时。"""
        self.timeout = timeout

    def send_binary(self, packet):
        """记录一个完整的二进制协议消息。"""
        self.sent.append(bytes(packet))

    def recv(self):
        """返回下一条预置输入消息。"""
        return self.incoming.pop(0)

    def ping(self, payload):
        """记录 Monitor 主动发送的心跳负载。"""
        self.pings.append(payload)

    def close(self):
        """把模拟连接标记为关闭。"""
        self.connected = False


class WebSocketDeviceTest(unittest.TestCase):
    """验证 WebSocket 设备与现有 PV1 读写框架的兼容性。"""

    def setUp(self):
        """注入模拟 websocket-client 模块并创建待测设备。"""
        self.socket = FakeWebSocket()
        self.websocket_module = types.SimpleNamespace(
            create_connection=lambda *args, **kwargs: self.socket,
            WebSocketException=FakeWebSocketException,
            WebSocketTimeoutException=FakeWebSocketTimeout,
        )
        self.module_patch = mock.patch.dict(sys.modules, {"websocket": self.websocket_module})
        self.module_patch.start()
        self.device = WebSocketDevice("ws://127.0.0.1:8765/pv1")

    def tearDown(self):
        """关闭设备并恢复原始模块表。"""
        self.device.close()
        self.module_patch.stop()

    def test_write_fragments_are_sent_as_one_message(self):
        """确认 CDC 分块写入会在换行处合并为一个 WebSocket 消息。"""
        self.device.write(b"PV1:PING")
        self.assertEqual(self.socket.sent, [])
        self.device.write(b":0:0000:\n")
        self.assertEqual(self.socket.sent, [b"PV1:PING:0:0000:\n"])

    def test_readline_and_close_follow_serial_contract(self):
        """确认读取返回完整 PV1 行且关闭后报告断开。"""
        self.assertEqual(self.device.readline(), b"PV1:PONG:0:0000:\n")
        self.device.close()
        self.assertFalse(self.device.is_open)

    def test_connection_failure_uses_reconnect_compatible_exception(self):
        """确认 WebSocket 初始握手失败会进入统一通信重连流程。"""
        websocket_module = types.SimpleNamespace(
            create_connection=mock.Mock(side_effect=FakeWebSocketException("远端连接丢失")),
            WebSocketException=FakeWebSocketException,
            WebSocketTimeoutException=FakeWebSocketTimeout,
        )
        with mock.patch.dict(sys.modules, {"websocket": websocket_module}):
            with self.assertRaisesRegex(serial.SerialException, "WebSocket 连接失败"):
                WebSocketDevice("ws://192.168.0.224:8765/pv1")


if __name__ == "__main__":
    unittest.main()
