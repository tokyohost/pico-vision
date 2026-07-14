"""验证 ESP32-S3 第一阶段时钟刷新和安全垃圾回收策略。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from main import Application  # noqa: E402
from styles.style_disk import DiskStyle  # noqa: E402
from timeIncrease import TimeIncrease  # noqa: E402


class RecordingRenderer:
    """记录应用安全垃圾回收调度器上报的耗时。"""

    def __init__(self):
        """创建空垃圾回收耗时记录。"""
        self.gc_us = []

    def record_gc_us(self, elapsed_us):
        """保存一次垃圾回收耗时。"""
        self.gc_us.append(elapsed_us)


class Esp32ClockRenderTest(unittest.TestCase):
    """覆盖绝对刷新点、默认样式脏区和 GC 保护窗口。"""

    def test_next_refresh_uses_absolute_calibration_boundary(self):
        """确认刷新延迟不会累加到下一次绝对周期边界。"""
        increase = TimeIncrease()
        increase._base_ticks = 100
        with mock.patch(
            "timeIncrease.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ), mock.patch(
            "timeIncrease.time.ticks_add",
            side_effect=lambda value, delta: value + delta,
            create=True,
        ):
            next_refresh = increase.next_refresh_ms(1000, now_ms=2250)

        self.assertEqual(next_refresh, 3100)

    def test_disk_time_change_only_refreshes_footer(self):
        """确认只有时间推进时默认磁盘样式仅刷新页脚。"""
        previous = {
            "timestamp": "2026-07-14T15:57:37",
            "uptime_seconds": 100,
            "network": {"ping_ms": 10, "online": True},
        }
        current = dict(previous)
        current["timestamp"] = "2026-07-14T15:57:38"
        current["uptime_seconds"] = 101

        regions = DiskStyle.select_dirty_regions(previous, current)

        self.assertEqual(regions, [("footer", 8, 286, 224, 25)])

    def test_disk_data_changes_select_corresponding_regions(self):
        """确认监控数据变化仍能选择所有对应动态区域。"""
        previous = {
            "disk": {"percent": 10},
            "cpu": {"percent": 10, "temperature_c": 30},
            "memory": {"percent": 20},
            "network": {
                "upload_bps": 1,
                "upload_history": [1],
                "download_bps": 2,
                "download_history": [2],
                "ping_ms": 3,
                "online": True,
            },
            "display": {"network_unit": "MB"},
        }
        current = {
            "disk": {"percent": 11},
            "cpu": {"percent": 12, "temperature_c": 31},
            "memory": {"percent": 21},
            "network": {
                "upload_bps": 4,
                "upload_history": [1, 4],
                "download_bps": 5,
                "download_history": [2, 5],
                "ping_ms": 6,
                "online": True,
            },
            "display": {"network_unit": "MB"},
        }

        regions = DiskStyle.select_dirty_regions(previous, current)

        self.assertEqual(
            [region[0] for region in regions],
            [
                "disk_summary",
                "cpu",
                "memory",
                "network_up",
                "network_down",
                "footer",
            ],
        )

    def test_gc_waits_when_clock_boundary_is_near(self):
        """确认整秒保护窗口内不会主动执行垃圾回收。"""
        application = Application.__new__(Application)
        application._next_gc = 1000
        application._next_clock_render = 2000
        application._renderer = RecordingRenderer()
        with mock.patch(
            "main.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ), mock.patch("main.gc.collect") as collect:
            collected = application._collect_garbage_if_safe(1950)

        self.assertFalse(collected)
        collect.assert_not_called()
        self.assertEqual(application._renderer.gc_us, [])

    def test_gc_runs_after_interval_outside_clock_guard(self):
        """确认远离整秒边界时执行垃圾回收并记录耗时。"""
        application = Application.__new__(Application)
        application._next_gc = 1000
        application._next_clock_render = 2000
        application._renderer = RecordingRenderer()
        with mock.patch(
            "main.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ), mock.patch(
            "main.time.ticks_us",
            side_effect=[100, 180],
            create=True,
        ), mock.patch(
            "main.time.ticks_ms", return_value=1200, create=True
        ), mock.patch(
            "main.time.ticks_add",
            side_effect=lambda value, delta: value + delta,
            create=True,
        ), mock.patch("main.gc.collect") as collect:
            collected = application._collect_garbage_if_safe(1200)

        self.assertTrue(collected)
        collect.assert_called_once_with()
        self.assertEqual(application._renderer.gc_us, [80])
        self.assertGreater(application._next_gc, 1200)


if __name__ == "__main__":
    unittest.main()
