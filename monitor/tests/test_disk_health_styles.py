#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""验证横屏磁盘样式的健康等级告警颜色与逐帧刷新行为。"""


import sys
import unittest
from pathlib import Path


PICO_SOURCE = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_SOURCE) not in sys.path:
    sys.path.insert(0, str(PICO_SOURCE))

from config import BLUE, GRAY, RED, YELLOW  # noqa: E402
from canvas import Canvas  # noqa: E402
from styles.style_horizontal_disk import HorizontalDiskStyle  # noqa: E402
from styles.style_horizontal_disk4x_qb import HorizontalDisk4xQbStyle  # noqa: E402
from styles.style_horizontal_disk6x import (  # noqa: E402
    ELEMENT_DANGER,
    ELEMENT_SUCCESS,
    ELEMENT_WARNING,
    HorizontalDisk6xStyle,
)
from styles.style_simple import SimpleStyle  # noqa: E402


class HistoryCanvas:
    """记录历史图绘制颜色，避免测试依赖真实 LCD 画布。"""

    def __init__(self):
        """初始化线段颜色记录。"""
        self.lines = []

    def pixel(self, x, y, color):
        """忽略测试无关的点阵背景像素。"""
        del x, y, color

    def line(self, x1, y1, x2, y2, color):
        """记录面积图每一列的坐标和颜色。"""
        self.lines.append((x1, y1, x2, y2, color))

    def draw_grid(self, x, y, width, height, step_x, step_y, color):
        """忽略图表组件生成的点阵背景。"""
        del x, y, width, height, step_x, step_y, color

    def draw_columns(self, columns, bottom=None):
        """记录图表组件生成的连续采样列。"""
        for x, y, color in columns:
            self.line(x, y, x, y if bottom is None else bottom, color)

    def draw_line_chart(self, definition, values):
        """复用 Python 兼容策略验证图表定义和颜色区间。"""
        Canvas.draw_line_chart(self, definition, values)


class DiskHealthStyleTest(unittest.TestCase):
    """验证三列和双列磁盘卡片采用一致的健康告警规则。"""

    def test_health_colors_switch_once_per_frame(self):
        """验证三级、四级和五级告警在相邻帧之间切换预期状态。"""
        for style_type in (HorizontalDiskStyle, HorizontalDisk6xStyle):
            style = style_type()
            self.assertEqual(style._health_display(3, 123)[:2], (GRAY, GRAY))
            self.assertEqual(style._health_display(4, 123)[:2], (YELLOW, YELLOW))
            self.assertEqual(style._health_display(5, 123), (RED, RED, False, True))

            style.begin_frame()

            self.assertEqual(style._health_display(3, 123)[:2], (YELLOW, YELLOW))
            self.assertEqual(style._health_display(4, 123)[:2], (RED, RED))
            self.assertEqual(style._health_display(5, 123), (RED, RED, True, False))

    def test_health_alarm_rows_are_refreshed_without_data_changes(self):
        """验证健康等级达到三级后，即使数据不变也会刷新所在磁盘行。"""
        cases = ((HorizontalDiskStyle, 3), (HorizontalDisk6xStyle, 2))
        for style_type, disks_per_row in cases:
            disks = [{"name": "DISK{}".format(index), "health": 1} for index in range(disks_per_row * 3)]
            disks[-1]["health"] = 3
            snapshot = {"physical_disks": disks}

            regions = style_type.select_dirty_regions(snapshot, snapshot)

            self.assertIn("disk_row_2", [region[0] for region in regions])

    def test_six_disk_rows_use_available_vertical_space(self):
        """Six-disk cards should extend near the footer with two-pixel gaps."""
        rows = [
            region
            for region in HorizontalDisk6xStyle.create_dirty_regions()
            if region[0].startswith("disk_row_")
        ]

        self.assertEqual(
            [(row[2], row[4]) for row in rows],
            [(49, 52), (103, 52), (157, 52)],
        )
        self.assertEqual(rows[-1][2] + rows[-1][4], 209)

    def test_memory_bar_requests_rounded_progress_style(self):
        """The MEM progress bar should use rounded fills, not panel corners."""
        class BarCanvas:
            def __init__(self):
                self.rounded = []

            def fill_round_rect(self, *args):
                self.rounded.append(args)

        canvas = BarCanvas()
        HorizontalDisk6xStyle()._bar(
            canvas, 7, 96, 90, 10, 50, BLUE, rounded=True
        )

        self.assertEqual(len(canvas.rounded), 2)

    def test_rectangular_bar_uses_flat_low_resolution_track(self):
        """Square bars should use a clean inset track without heavy borders."""
        class FlatBarCanvas:
            def __init__(self):
                self.rectangles = []

            def fill_rect(self, *args):
                self.rectangles.append(args)

        canvas = FlatBarCanvas()
        HorizontalDisk6xStyle()._bar(
            canvas, 112, 33, 200, 8, 50, BLUE
        )

        self.assertEqual(canvas.rectangles[0][:4], (112, 34, 200, 6))
        self.assertEqual(canvas.rectangles[1][:4], (112, 34, 100, 6))


class CpuHistoryColorTest(unittest.TestCase):
    """验证两种横屏样式的 CPU 峰值颜色会保留在对应历史位置。"""

    def test_cpu_history_uses_color_for_each_historical_value(self):
        """验证绿色、黄色和红色条带同时存在，而不是整图跟随当前值变色。"""
        for style_type in (HorizontalDiskStyle, HorizontalDisk6xStyle):
            canvas = HistoryCanvas()
            style = style_type()

            style._history(
                canvas, 0, 0, 31, 20,
                [10, 10, 60, 60, 90, 90], ELEMENT_DANGER,
                percentage=True, filled=True, color_by_value=True,
            )

            colors = {line[-1] for line in canvas.lines}
            self.assertTrue({ELEMENT_SUCCESS, ELEMENT_WARNING, ELEMENT_DANGER}.issubset(colors))
            red_columns = {line[0] for line in canvas.lines if line[-1] == ELEMENT_DANGER}
            all_columns = {line[0] for line in canvas.lines}
            self.assertLess(len(red_columns), len(all_columns))

    def test_chart_color_callback_uses_hash_cache(self):
        """验证同一数值区间只调用一次颜色回调并复用哈希缓存。"""
        canvas = HistoryCanvas()
        callback_values = []

        def color_callback(value):
            """记录回调数值并返回测试颜色。"""
            callback_values.append(value)
            return ELEMENT_DANGER if value >= 50 else ELEMENT_SUCCESS

        canvas.draw_line_chart({
            "x": 0, "y": 0, "width": 10, "height": 10,
            "maximum": 100, "color": ELEMENT_SUCCESS, "filled": True,
            "color_callback": color_callback, "color_cache_step": 100,
            "grid_step_x": 0, "grid_step_y": 0, "grid_color": 0,
        }, [10, 90])

        self.assertEqual(len(callback_values), 1)
        self.assertEqual(len(canvas.lines), 10)


class QbittorrentStyleTest(unittest.TestCase):
    """验证四磁盘 qBittorrent 样式的注册名称和局部刷新规则。"""

    def test_qbittorrent_change_refreshes_replaced_panel(self):
        """确认 qBittorrent 数据变化只会触发原网络详情区域刷新。"""
        previous = {"qbittorrent": {"online": False}}
        current = {"qbittorrent": {"online": True}}

        regions = HorizontalDisk4xQbStyle.select_dirty_regions(previous, current)

        self.assertEqual(HorizontalDisk4xQbStyle.name, "horizontal_disk4x_qb")
        self.assertIn("network_details", [region[0] for region in regions])

    def test_network_rate_change_refreshes_only_its_small_region(self):
        """A changed upload rate must not repaint both history charts."""
        previous = {"network": {"upload_bps": 100, "download_bps": 200}}
        current = {"network": {"upload_bps": 101, "download_bps": 200}}

        regions = HorizontalDisk4xQbStyle.select_dirty_regions(
            previous, current
        )

        self.assertEqual([region[0] for region in regions], ["network_values"])

    def test_cpu_history_change_does_not_repaint_cpu_values(self):
        """History-only changes should update only the graph viewport."""
        previous = {"cpu": {"percent": 10, "history": [10, 11]}}
        current = {"cpu": {"percent": 10, "history": [11, 12]}}

        regions = HorizontalDisk4xQbStyle.select_dirty_regions(
            previous, current
        )

        self.assertEqual([region[0] for region in regions], ["cpu_history"])

    def test_storage_percent_uses_two_decimals_and_cpu_scale(self):
        """The disk percentage should retain precision at CPU text scale."""
        class TextCanvas:
            def __init__(self):
                self.calls = []

            @staticmethod
            def text_width(value, scale=1):
                return len(value) * 6 * scale

            def text(self, x, y, value, color, scale=1):
                self.calls.append((x, y, value, color, scale))

        canvas = TextCanvas()
        HorizontalDisk4xQbStyle()._draw_storage_dirty(
            canvas, "storage_percent", {"disk": {"percent": 57.126}}
        )

        self.assertEqual(canvas.calls[0][2], "57.13%")
        self.assertEqual(canvas.calls[0][4], 2)
        self.assertEqual(canvas.calls[0][0], 312 - 12 * len("57.13%"))


class SimpleStyleTest(unittest.TestCase):
    """验证简洁样式的磁盘筛选和渐变面积图规则。"""

    def test_unhealthy_disks_are_selected_first_and_limited_to_three(self):
        """确认健康等级较差的磁盘优先显示且最多显示三块。"""
        snapshot = {
            "physical_disks": [
                {"name": "D0", "health": 1},
                {"name": "D1", "health": 4},
                {"name": "D2", "health": 2},
                {"name": "D3", "health": 5},
            ]
        }

        selected = SimpleStyle._selected_disks(snapshot)

        self.assertEqual([disk["name"] for disk in selected], ["D3", "D1", "D2"])

    def test_health_text_uses_element_status_colors(self):
        """确认六个健康等级使用对应的 Element 状态颜色。"""
        self.assertEqual(
            [SimpleStyle._health_text_color(level) for level in range(6)],
            [GRAY, ELEMENT_SUCCESS, BLUE, ELEMENT_WARNING, ELEMENT_DANGER, RED],
        )

    def test_gradient_history_uses_multiple_color_levels(self):
        """确认实心面积图从折线到底部使用多个渐变颜色层级。"""
        class GradientCanvas:
            """记录渐变图绘制时使用的像素和线段颜色。"""

            def __init__(self):
                """初始化颜色记录列表。"""
                self.colors = []
                self.pixel_calls = 0

            def pixel(self, x, y, color):
                """记录单个渐变像素颜色。"""
                del x, y
                self.pixel_calls += 1
                self.colors.append(color)

            def line(self, x1, y1, x2, y2, color):
                """记录折线颜色。"""
                del x1, y1, x2, y2
                self.colors.append(color)

            def fill_rect(self, x, y, width, height, color):
                """记录渐变色带矩形颜色。"""
                del x, y, width, height
                self.colors.append(color)

        canvas = GradientCanvas()

        SimpleStyle()._gradient_history(canvas, 0, 0, 20, 12, [10, 80, 30], BLUE, True)

        self.assertGreater(len(set(canvas.colors)), 3)
        self.assertEqual(canvas.pixel_calls, 0)


if __name__ == "__main__":
    unittest.main()
