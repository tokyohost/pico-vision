"""验证系统启动页固定展示 Wi-Fi 与 WebSocket 状态。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from main import Application
from styles.style_boot import BootStyle


class FakeTransport:
    """提供启动页测试所需的固定 Wi-Fi 状态。"""

    def wifi_status(self):
        """返回已经连接无线网络但尚无 WebSocket 客户端的状态。"""
        return {
            "enabled": True,
            "available": True,
            "connected": True,
            "ssid": "Home-WiFi",
            "ip": "192.168.1.20",
            "rssi": -42,
            "websocket_port": 8765,
            "websocket_path": "/pv1",
            "websocket_connected": False,
        }


class BootWifiStatusTest(unittest.TestCase):
    """验证 Wi-Fi 信息固定区域的数据生成和文本格式。"""

    def test_application_exposes_transport_wifi_status(self):
        """确认启动快照可以读取传输管理器的实时 Wi-Fi 状态。"""
        application = Application.__new__(Application)
        application._transport = FakeTransport()

        self.assertEqual(
            application._boot_wifi_status()["ip"],
            "192.168.1.20",
        )

    def test_boot_style_builds_fixed_wifi_lines(self):
        """确认启动样式生成四行固定 Wi-Fi 与 WebSocket 信息。"""
        lines = BootStyle._wifi_lines(FakeTransport().wifi_status())

        self.assertEqual(lines, (
            "WIFI: CONNECTED  RSSI:-42",
            "SSID: Home-WiFi",
            "IP: 192.168.1.20",
            "WS: 192.168.1.20:8765/pv1 WAITING",
        ))

    def test_wifi_disabled_hides_fixed_area(self):
        """确认关闭 Wi-Fi 时不显示无线网络固定区域。"""
        self.assertEqual(BootStyle._wifi_lines({"enabled": False}), ())


if __name__ == "__main__":
    unittest.main()
