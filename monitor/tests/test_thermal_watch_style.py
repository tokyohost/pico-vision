"""验证 ESP32-S3 热力监控样式的结构和核心绘制内容。"""

import sys
import unittest
from pathlib import Path


ESP32_SOURCE = Path(__file__).resolve().parents[2] / "esp32-s3"
if str(ESP32_SOURCE) not in sys.path:
    sys.path.insert(0, str(ESP32_SOURCE))

from styles.style_plugins import create_style  # noqa: E402
from styles.style_thermal_watch import ThermalWatchStyle  # noqa: E402


class RecordingCanvas:
    """记录热力样式发出的基础绘图和趋势图指令。"""

    origin_y = 0
    height = 240

    def __init__(self):
        """初始化文本和趋势图调用记录。"""
        self.texts = []
        self.scaled_texts = []
        self.charts = []

    def clear(self, color):
        """忽略测试无关的背景清理。"""
        del color

    def line(self, x1, y1, x2, y2, color):
        """忽略测试无关的边框线。"""
        del x1, y1, x2, y2, color

    def fill_rect(self, x, y, width, height, color):
        """忽略测试无关的色块。"""
        del x, y, width, height, color

    def text_width(self, value, scale=1):
        """用紧凑字体近似宽度支持文本对齐。"""
        return len(str(value)) * 6 * scale

    def text(self, x, y, value, color, scale=1):
        """记录文本绘制内容。"""
        del x, y, color
        self.texts.append(str(value))
        self.scaled_texts.append((str(value), scale))

    def draw_line_chart(self, definition, values):
        """记录趋势图定义及其数据。"""
        self.charts.append((dict(definition), tuple(values)))


class ThermalWatchStyleTest(unittest.TestCase):
    """验证热力监控样式满足插件约定和用户布局要求。"""

    def test_style_metadata_and_region_capacity(self):
        """样式应正确注册且所有脏矩形适配四十行条带容量。"""
        style = create_style("thermal_watch")

        self.assertEqual(style.zh_name, "热力监控")
        self.assertEqual((style.width, style.height), (320, 240))
        self.assertTrue(style.landscape)
        for key, _x, _y, width, height in style.create_dirty_regions():
            self.assertLessEqual(width * height, 320 * 40, key)

    def test_draws_gpu_and_network_filled_histories_without_disk(self):
        """GPU 与双向网络应为实心图，页面不得绘制硬盘或环境温度。"""
        canvas = RecordingCanvas()
        snapshot = {
            "timestamp": "2026-07-15T15:35:20+08:00",
            "uptime_seconds": 42209,
            "cpu": {"percent": 46, "temperature_c": 91, "frequency_ghz": 3.97, "history": [80, 84, 82]},
            "gpu": {"percent": 3, "temperature_c": 44, "history": [1, 2, 3]},
            "memory": {"percent": 61.5, "used_bytes": 42.2 * 1024 ** 3, "total_bytes": 68.6 * 1024 ** 3},
            "power": {"watts": 93.3},
            "disk": {"percent": 77},
            "network": {
                "online": True, "ping_ms": 1, "ip": "192.168.1.8",
                "upload_bps": 2300, "download_bps": 2000,
                "upload_history": [1000, 2300], "download_history": [800, 2000],
            },
        }

        ThermalWatchStyle.draw_visible(canvas, snapshot)

        self.assertIn("THERMAL WATCH", canvas.texts)
        self.assertIn("GPU", canvas.texts)
        self.assertIn("NET", canvas.texts)
        self.assertNotIn("SSD", canvas.texts)
        self.assertNotIn("DISK", canvas.texts)
        self.assertNotIn("AMBIENT", canvas.texts)
        self.assertIn(("91℃", 4), canvas.scaled_texts)
        self.assertIn(("44℃", 2), canvas.scaled_texts)
        self.assertIn(("3%", 2), canvas.scaled_texts)
        self.assertNotIn("42.2G/68.6G", canvas.texts)
        self.assertEqual(len(canvas.charts), 4)
        self.assertTrue(all(definition["filled"] for definition, _values in canvas.charts))
        self.assertEqual(canvas.charts[1][1], (1, 2, 3))
        self.assertEqual(canvas.charts[2][1], (1000, 2300))
        self.assertEqual(canvas.charts[3][1], (800, 2000))

    def test_disk_only_change_does_not_trigger_refresh(self):
        """磁盘字段变化不应触发任何热力样式区域刷新。"""
        previous = {"disk": {"percent": 10}}
        current = {"disk": {"percent": 90}}

        self.assertEqual(ThermalWatchStyle.select_dirty_regions(previous, current), [])


if __name__ == "__main__":
    unittest.main()
