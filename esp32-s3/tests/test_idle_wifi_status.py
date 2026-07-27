"""验证待机页面始终使用设备本机的实时 Wi-Fi 状态。"""

import sys
import unittest
from pathlib import Path


ESP32_S3_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_S3_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_S3_ROOT))

from main import Application  # noqa: E402


class IdleWifiStatusTest(unittest.TestCase):
    """覆盖普通快照进入待机渲染入口时的 Wi-Fi 状态补全。"""

    def test_idle_render_replaces_stale_monitor_wifi_status(self):
        """确认待机态不会被上位机快照中的未连接状态反向覆盖。"""
        application = Application.__new__(Application)
        application._idle_active = True
        application._button_network_unit_override = None
        application._button_hint_until_ms = None
        application._button_hint_label = None
        application._boot_wifi_status = lambda: {
            "enabled": True,
            "connected": True,
            "ssid": "已连接网络",
            "rssi": -42,
        }
        snapshot = {
            "wifi": {"connected": False},
            "timestamp": "2026-07-27 10:20:30",
        }

        rendered = application._with_button_hint(snapshot)

        self.assertTrue(rendered["wifi"]["connected"])
        self.assertEqual("已连接网络", rendered["wifi"]["ssid"])
        self.assertFalse(snapshot["wifi"]["connected"])

    def test_normal_render_keeps_monitor_wifi_status(self):
        """确认非待机样式仍保持原快照内容，不引入额外设备查询。"""
        application = Application.__new__(Application)
        application._idle_active = False
        application._button_network_unit_override = None
        application._button_hint_until_ms = None
        application._button_hint_label = None
        snapshot = {"wifi": {"connected": False}}

        rendered = application._with_button_hint(snapshot)

        self.assertFalse(rendered["wifi"]["connected"])


if __name__ == "__main__":
    unittest.main()
