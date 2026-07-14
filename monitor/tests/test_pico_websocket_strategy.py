"""验证 Pico 端 WebSocket 策略的 MicroPython 兼容性。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from net.websocket import WebSocketTransport


class NonDeletingBytearray(bytearray):
    """模拟不支持项目删除的 RP2040 MicroPython 字节缓冲区。"""

    def __delitem__(self, key):
        """在测试中拒绝项目删除，以复现设备固件的运行时限制。"""
        del key
        raise TypeError("'bytearray' object doesn't support item deletion")


class FakeWifiManager:
    """提供 WebSocket 策略构造所需的最小 Wi-Fi 管理器。"""

    def is_connected(self):
        """始终报告 Wi-Fi 已连接。"""
        return True


class FakeClient:
    """提供已完成握手的最小 WebSocket 客户端替身。"""

    def close(self):
        """忽略测试中的关闭请求。"""


class PicoWebSocketStrategyTest(unittest.TestCase):
    """确认设备端缓冲消费不依赖 bytearray 项删除。"""

    @staticmethod
    def _masked_binary_frame(payload):
        """构造一个客户端发送的短掩码二进制 WebSocket 帧。"""
        mask = b"\x11\x22\x33\x44"
        masked_payload = bytes(
            value ^ mask[index & 3]
            for index, value in enumerate(payload)
        )
        return bytes((0x82, 0x80 | len(payload))) + mask + masked_payload

    def test_frame_parse_and_read_do_not_delete_bytearray_items(self):
        """解帧和读取均应兼容不支持项目删除的 bytearray。"""
        transport = WebSocketTransport(FakeWifiManager())
        transport._client = FakeClient()
        transport._http_buffer = None
        payload = b"PV1:PING:0:0000:\n"
        transport._wire_buffer = NonDeletingBytearray(
            self._masked_binary_frame(payload)
        )

        transport._parse_frames()

        self.assertEqual(len(payload), transport.available())
        transport._receive_buffer = NonDeletingBytearray(
            transport._receive_buffer
        )
        output = bytearray(len(payload))
        count = transport.readinto(output)
        self.assertEqual(payload, bytes(output[:count]))
        self.assertEqual(0, transport.available())


if __name__ == "__main__":
    unittest.main()
