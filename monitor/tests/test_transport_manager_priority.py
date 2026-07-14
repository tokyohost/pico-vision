"""验证设备端传输管理器始终将 USB 置于 WebSocket 之前。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from net.manager import TransportManager


class FakeTransport:
    """提供可切换连接状态并记录调用次数的传输策略替身。"""

    def __init__(self, name, connected=False):
        """保存传输名称、初始连接状态和空调用计数。"""
        self.name = name
        self.connected = connected
        self.update_count = 0
        self.close_count = 0

    def update(self):
        """记录一次传输状态推进。"""
        self.update_count += 1

    def is_connected(self):
        """返回当前模拟连接状态。"""
        return self.connected

    def close(self):
        """记录关闭操作并断开当前模拟连接。"""
        self.close_count += 1
        self.connected = False


class TransportManagerPriorityTest(unittest.TestCase):
    """确认 USB 连接会抢占并暂停 Wi-Fi WebSocket。"""

    @staticmethod
    def _build_manager(usb_transport, wifi_transport, active=None):
        """绕过硬件构造过程，组装只包含模拟策略的管理器。"""
        manager = TransportManager.__new__(TransportManager)
        manager.wifi_enabled = True
        manager.wifi = None
        manager._usb_transport = usb_transport
        manager._wifi_transport = wifi_transport
        manager._strategies = [usb_transport, wifi_transport]
        manager._active = active
        return manager

    def test_usb_connection_preempts_active_websocket(self):
        """Wi-Fi 已连接时，USB 成功连接应立即接管并关闭 WebSocket。"""
        usb_transport = FakeTransport("usb", connected=True)
        wifi_transport = FakeTransport("wifi", connected=True)
        manager = self._build_manager(
            usb_transport,
            wifi_transport,
            active=wifi_transport,
        )

        manager._update_selection()

        self.assertIs(usb_transport, manager._active)
        self.assertEqual(1, wifi_transport.close_count)
        self.assertEqual(0, wifi_transport.update_count)

    def test_connected_usb_keeps_websocket_suspended(self):
        """USB 持续连接期间不应推进或重新接受 WebSocket 会话。"""
        usb_transport = FakeTransport("usb", connected=True)
        wifi_transport = FakeTransport("wifi", connected=False)
        manager = self._build_manager(
            usb_transport,
            wifi_transport,
            active=usb_transport,
        )

        manager._update_selection()
        manager._update_selection()

        self.assertIs(usb_transport, manager._active)
        self.assertEqual(0, wifi_transport.update_count)
        self.assertEqual(0, wifi_transport.close_count)

    def test_websocket_resumes_after_usb_disconnects(self):
        """USB 断开后应恢复 WebSocket 推进并选择已建立的 Wi-Fi 会话。"""
        usb_transport = FakeTransport("usb", connected=False)
        wifi_transport = FakeTransport("wifi", connected=True)
        manager = self._build_manager(
            usb_transport,
            wifi_transport,
            active=usb_transport,
        )

        manager._update_selection()

        self.assertIs(wifi_transport, manager._active)
        self.assertEqual(1, wifi_transport.update_count)


if __name__ == "__main__":
    unittest.main()
