"""验证横屏磁盘样式的健康等级告警颜色与逐帧刷新行为。"""

import sys
import unittest
from pathlib import Path


PICO_SOURCE = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_SOURCE) not in sys.path:
    sys.path.insert(0, str(PICO_SOURCE))

from config import GRAY, RED, YELLOW  # noqa: E402
from style_horizontal_disk import HorizontalDiskStyle  # noqa: E402
from style_horizontal_disk4x_qb import HorizontalDisk4xQbStyle  # noqa: E402
from style_horizontal_disk6x import (  # noqa: E402
    ELEMENT_DANGER,
    ELEMENT_SUCCESS,
    ELEMENT_WARNING,
    HorizontalDisk6xStyle,
)


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


class QbittorrentStyleTest(unittest.TestCase):
    """验证四磁盘 qBittorrent 样式的注册名称和局部刷新规则。"""

    def test_qbittorrent_change_refreshes_replaced_panel(self):
        """确认 qBittorrent 数据变化只会触发原网络详情区域刷新。"""
        previous = {"qbittorrent": {"online": False}}
        current = {"qbittorrent": {"online": True}}

        regions = HorizontalDisk4xQbStyle.select_dirty_regions(previous, current)

        self.assertEqual(HorizontalDisk4xQbStyle.name, "horizontal_disk4x_qb")
        self.assertIn("network_details", [region[0] for region in regions])


if __name__ == "__main__":
    unittest.main()
