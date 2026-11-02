"""验证待机页面始终使用设备本机的实时 Wi-Fi 状态。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ESP32_S3_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_S3_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_S3_ROOT))

from main import Application  # noqa: E402
from canvas import Canvas  # noqa: E402
import font_builtin  # noqa: E402
from styles.style_idle import IdleStyle, IDLE_GREEN, DIM_TEXT  # noqa: E402


class IdleWifiSignalTest(unittest.TestCase):
    """使用实际画布验证信号档位、文字布局及刷新后的像素结果。"""

    def setUp(self):
        """模拟固件字体接口，使用十二像素字高和实际半角、全角步进。"""
        native = Mock(api_version=lambda: 10)
        native.text_width.side_effect = lambda kind, text, scale: sum(6 if ord(c) < 128 else 12 for c in text) * scale
        native.font_glyph.return_value = (0x1FE,) * 5
        patcher = patch.object(font_builtin, "_native_canvas", native)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_signal_levels_and_invalid_values(self):
        """检查四档边界与异常数据，避免未知信号被显示为满格。"""
        cases = ((-42, 4), (-55, 4), (-56, 3), (-65, 3), (-66, 2),
                 (-75, 2), (-76, 1), (-100, 1), (None, 0), ("bad", 0),
                 ("-55", 0), (True, 0), (0, 0), (1, 0), (-128, 0),
                 (float("nan"), 0), (float("inf"), 0))
        for rssi, expected in cases:
            with self.subTest(rssi=rssi):
                canvas = Canvas(320, 40)
                with patch.object(canvas, "fill_rect", wraps=canvas.fill_rect) as rectangles:
                    IdleStyle._draw_header(canvas, {"wifi": {
                        "connected": True, "ssid": "Home", "rssi": rssi}})
                bars = [call.args for call in rectangles.call_args_list if call.args[2] == 3]
                self.assertEqual([3, 6, 9, 12], [bar[3] for bar in bars])
                self.assertEqual([18] * 4, [bar[1] + bar[3] for bar in bars])
                self.assertEqual([bars[0][0] + i * 5 for i in range(4)], [bar[0] for bar in bars])
                self.assertEqual([IDLE_GREEN] * expected + [DIM_TEXT] * (4 - expected),
                                 [bar[4] for bar in bars])

    def test_header_layout_and_disconnected_state(self):
        """检查长中英文名称裁剪、无数值标签及断网时的灰色图标。"""
        for wifi in ({"connected": True, "ssid": "Home" * 30, "rssi": -55},
                     {"connected": True, "ssid": "中文网络" * 20},
                     {"connected": False, "rssi": -42}):
            canvas = Canvas(320, 40)
            canvas.set_font("screen_2inch")
            with patch.object(canvas, "text") as text, patch.object(canvas, "fill_rect") as rectangles:
                IdleStyle._draw_header(canvas, {"wifi": wifi})
            x, y, label, _ = text.call_args.args
            self.assertEqual("zlabs_pixel_12px", text.call_args.kwargs["font_name"])
            bars = [call.args for call in rectangles.call_args_list]
            self.assertGreaterEqual(bars[0][0], 104)
            self.assertEqual(bars[-1][0] + 3 + 6, x)
            self.assertEqual(312, x + canvas.text_width(label, font_name="zlabs_pixel_12px"))
            self.assertTrue(all(bar[1] + bar[3] == y + 10 for bar in bars))
            self.assertNotIn("dBm", label)
            self.assertNotIn("RSSI", label)
            if not wifi["connected"]:
                self.assertEqual("WIFI NOT CONNECT", label)
                self.assertTrue(all(bar[4] == DIM_TEXT for bar in bars))

    def test_signal_and_name_changes_leave_no_stale_pixels(self):
        """比较连续刷新与新画布的结果，防止降档和名称变短留下残影。"""
        canvas = Canvas(320, 240)
        for wifi in ({"connected": True, "ssid": "LongNetworkName", "rssi": -42},
                     {"connected": True, "ssid": "Home", "rssi": -80},
                     {"connected": True, "ssid": "Home"}, {"connected": False}):
            snapshot = {"wifi": wifi}
            IdleStyle.draw_dirty(canvas, "idle_0", snapshot)
            fresh = Canvas(320, 240)
            IdleStyle.draw_visible(fresh, snapshot)
            self.assertEqual(fresh.buffer, canvas.buffer)


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
