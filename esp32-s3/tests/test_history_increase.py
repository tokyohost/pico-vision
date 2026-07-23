"""验证 ESP32-S3 缺秒历史保持末值与真实数据覆盖行为。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


ESP32_S3_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_S3_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_S3_ROOT))

from historyIncrease import HistoryIncrease  # noqa: E402
from data_receiver import SnapshotCache  # noqa: E402


class HistoryIncreaseTest(unittest.TestCase):
    """覆盖普通历史、嵌套历史和连续缺秒的处理结果。"""

    def test_missing_second_repeats_latest_value(self):
        """确认下一秒没有真实快照时历史序列右移并复制末值。"""
        increase = HistoryIncrease()
        snapshot = {"cpu": {"history": [10, 20, 30]}}
        increase.receive(None, snapshot, 0)

        increase.increase(snapshot, 1)

        self.assertEqual(snapshot["cpu"]["history"], [20, 30, 30])

    def test_real_data_replaces_repeated_value_in_same_second(self):
        """确认本秒真实数据到达后只覆盖末尾保持值。"""
        increase = HistoryIncrease()
        previous = {"cpu": {"history": [10, 20, 30]}}
        increase.receive(None, previous, 0)
        increase.increase(previous, 1)
        incoming = {"cpu": {"history": [20, 30, 45]}}

        normalized = increase.receive(previous, incoming, 1)

        self.assertEqual(normalized["cpu"]["history"], [20, 30, 45])

    def test_multiple_missing_seconds_repeat_latest_value(self):
        """确认一次跨过多秒时按固定时间格重复最近值。"""
        increase = HistoryIncrease()
        snapshot = {"network": {"upload_history": [1, 2, 3, 4]}}
        increase.receive(None, snapshot, 0)

        increase.increase(snapshot, 3)

        self.assertEqual(snapshot["network"]["upload_history"], [4, 4, 4, 4])

    def test_nested_disk_history_uses_stable_identity(self):
        """确认磁盘顺序变化时真实速率仍覆盖对应磁盘的保持值。"""
        increase = HistoryIncrease()
        previous = {
            "physical_disks": [
                {"name": "A", "read_history": [1, 2]},
                {"name": "B", "read_history": [3, 4]},
            ]
        }
        increase.receive(None, previous, 0)
        increase.increase(previous, 1)
        incoming = {
            "physical_disks": [
                {"name": "B", "read_history": [4, 8]},
                {"name": "A", "read_history": [2, 6]},
            ]
        }

        normalized = increase.receive(previous, incoming, 1)

        self.assertEqual(
            normalized["physical_disks"],
            [
                {"name": "B", "read_history": [4, 8]},
                {"name": "A", "read_history": [2, 6]},
            ],
        )

    def test_snapshot_cache_replaces_repeated_value_with_real_value(self):
        """确认缓存先保持末值，随后由同秒真实 Monitor 数据覆盖末点。"""
        clock = [100]
        with mock.patch(
            "timeIncrease.time.ticks_ms",
            side_effect=lambda: clock[0],
            create=True,
        ), mock.patch(
            "timeIncrease.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ):
            cache = SnapshotCache()
            cache.update({
                "timestamp": "2026-07-23T12:00:00+08:00",
                "uptime_seconds": 100,
                "cpu": {"history": [10, 20, 30]},
            })
            clock[0] = 1100
            projected, _version = cache.latest()
            self.assertEqual(projected["cpu"]["history"], [20, 30, 30])

            clock[0] = 1200
            cache.update({
                "timestamp": "2026-07-23T12:00:01+08:00",
                "uptime_seconds": 101,
                "cpu": {"history": [20, 30, 45]},
            })
            actual, _version = cache.latest()

        self.assertEqual(actual["cpu"]["history"], [20, 30, 45])


if __name__ == "__main__":
    unittest.main()
