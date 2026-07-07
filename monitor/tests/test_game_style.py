"""验证游戏监控简约样式的注册元数据、刷新选择和绘制行为。"""

import sys
import unittest
from pathlib import Path


PICO_SOURCE = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_SOURCE) not in sys.path:
    sys.path.insert(0, str(PICO_SOURCE))

from styles.style_game import GameStyle  # noqa: E402
from styles.style_game import GAME_ORANGE  # noqa: E402
from styles.style_plugins import create_style  # noqa: E402
from config import GRAY, GREEN, RED, YELLOW  # noqa: E402


class RecordingCanvas:
    """记录样式绘制调用，隔离真实 LCD 和字体依赖。"""

    def __init__(self):
        """初始化文本、线条、矩形和图表调用记录。"""
        self.texts = []
        self.charts = []
        self.lines = []

    def clear(self, color):
        """忽略测试无关的背景清理颜色。"""
        del color

    def fill_rect(self, x, y, width, height, color):
        """忽略测试无关的卡片边框像素。"""
        del x, y, width, height, color

    def line(self, x1, y1, x2, y2, color):
        """记录直线位置和颜色，供平均帧参考线断言使用。"""
        self.lines.append((x1, y1, x2, y2, color))

    def text_width(self, value, scale=1):
        """使用紧凑字体的近似宽度支持对齐计算。"""
        return len(str(value)) * 6 * scale

    def text(self, x, y, value, color, scale=1):
        """记录文本内容与绘制位置。"""
        del color, scale
        self.texts.append((x, y, str(value)))

    def draw_line_chart(self, definition, values):
        """记录趋势图定义和采样值。"""
        self.charts.append((dict(definition), tuple(values)))


class GameStyleTest(unittest.TestCase):
    """验证游戏监控样式满足插件约定和核心设计内容。"""

    def test_style_metadata_and_registration(self):
        """样式应以 game 名称注册并提供指定中文名称。"""
        style = create_style("game")

        self.assertEqual(style.name, "game")
        self.assertEqual(style.zh_name, "游戏监控简约")
        self.assertTrue(style.landscape)
        self.assertEqual((style.width, style.height), (320, 240))

    def test_dirty_regions_fit_strip_canvas_capacity(self):
        """每个脏矩形的像素数都不得超过四十行条带画布容量。"""
        capacity_pixels = 320 * 40

        for key, _x, _y, width, height in GameStyle.create_dirty_regions():
            self.assertLessEqual(
                width * height,
                capacity_pixels,
                "{} 脏矩形超过画布容量".format(key),
            )

    def test_dirty_regions_only_follow_visible_fields(self):
        """不可见字段不刷新，单项指标变化仅刷新对应摘要和图表。"""
        previous = {"timestamp": "2026-07-07T09:07:00", "cpu": {"percent": 49}}
        unrelated = dict(previous, network={"upload_bps": 1})
        changed = dict(previous, cpu={"percent": 50})

        self.assertEqual(GameStyle.select_dirty_regions(previous, unrelated), [])
        self.assertEqual(
            [region[0] for region in GameStyle.select_dirty_regions(previous, changed)],
            ["cpu_summary", "cpu_chart"],
        )
        history_changed = dict(
            previous,
            cpu={"percent": 49, "history": [48, 49]},
        )
        self.assertEqual(
            [
                region[0]
                for region in GameStyle.select_dirty_regions(previous, history_changed)
            ],
            ["cpu_chart"],
        )

    def test_dirty_draw_only_renders_selected_component(self):
        """摘要区域刷新不应重复计算和绘制任何历史趋势图。"""
        canvas = RecordingCanvas()
        snapshot = {
            "cpu": {"percent": 49, "frequency_ghz": 3.8, "history": [48, 49]},
        }

        GameStyle.draw_dirty(canvas, "cpu_summary", snapshot)

        self.assertEqual(canvas.charts, [])
        self.assertIn((171, 34, "CPU"), canvas.texts)

    def test_usage_percentage_colors_follow_load_levels(self):
        """CPU、GPU 和内存百分比应共用四级负载颜色规则。"""
        self.assertEqual(GameStyle._usage_color(None), GRAY)
        self.assertEqual(GameStyle._usage_color(59), GREEN)
        self.assertEqual(GameStyle._usage_color(60), YELLOW)
        self.assertEqual(GameStyle._usage_color(80), GAME_ORANGE)
        self.assertEqual(GameStyle._usage_color(90), RED)

    def test_draws_design_metrics_and_six_trend_layers(self):
        """完整绘制应包含设计稿指标，并为三张图绘制填充层和折线层。"""
        canvas = RecordingCanvas()
        history = [49, 50, 48]
        snapshot = {
            "timestamp": "2026-07-07T09:07:00+08:00",
            "fps": {
                "value": 60,
                "history": [50, 60, 70],
                "process_name": "Black Myth Wukong",
            },
            "cpu": {"percent": 49, "frequency_ghz": 3.8, "history": history},
            "gpu": {
                "percent": 2,
                "history": [1, 2, 2],
                "dedicated_memory_used_bytes": 4 * 1024 ** 3,
                "dedicated_memory_total_bytes": 4 * 1024 ** 3,
            },
            "memory": {
                "percent": 65,
                "used_bytes": 41.6 * 1024 ** 3,
                "total_bytes": 63.9 * 1024 ** 3,
                "history": [64, 65, 65],
            },
        }

        GameStyle.draw_visible(canvas, snapshot)

        values = [item[2] for item in canvas.texts]
        self.assertIn("BLACK MYTH WUKONG", values)
        self.assertNotIn("ACTIVE", values)
        self.assertIn("MIN", values)
        self.assertIn("AVG", values)
        self.assertIn("MAX", values)
        self.assertEqual(values.count("60"), 2)
        self.assertIn("3.8GHz", values)
        self.assertIn("4/4G", values)
        self.assertIn("41.6/63.9G", values)
        self.assertEqual(len(canvas.charts), 8)
        self.assertIn((13, 122, 151, 122, 0xE71C), canvas.lines)
        self.assertIn((171, 34, "CPU"), canvas.texts)
        self.assertIn((273, 34, "49%"), canvas.texts)
        self.assertIn((273, 54, "3.8GHz"), canvas.texts)


if __name__ == "__main__":
    unittest.main()
