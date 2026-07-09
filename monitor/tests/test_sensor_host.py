"""SensorHost 生命周期和采集转换测试。"""

import unittest
from types import SimpleNamespace
from unittest import mock

from collectTask.tasks.sensor_host import SensorHostTask


class SensorHostTaskTest(unittest.TestCase):
    """验证 SensorHost 采集任务的标准字段转换。"""

    def test_collect_converts_snapshot_to_monitor_fragment(self):
        """确认 SensorHost 快照会转换为 CPU、GPU、功耗和磁盘字段。"""
        collector = SimpleNamespace(
            sensor_host=mock.Mock(),
            histories={"cpu": [], "memory": []},
            history_states={},
            gpu_history=[],
            power_history=[],
            _disk_task_snapshot={"disk": {}, "disks": [], "physical_disks": []},
        )
        collector.sensor_host.snapshot.return_value = {
            "cpu": {"percent": 12.3, "frequency_ghz": 4.2, "temperature_c": 55.0},
            "gpu": {
                "name": "GPU",
                "percent": 45,
                "temperature_c": 60,
                "dedicated_memory_used_bytes": 1024,
                "dedicated_memory_total_bytes": 2048,
            },
            "power": {"watts": 88.8, "source": "librehardwaremonitor", "scope": "cpu_gpu"},
            "disks": [{"name": "Disk0", "temperature_c": 40}],
        }

        with mock.patch("collectTask.tasks.sensor_host.platform.system", return_value="Windows"):
            fragment = SensorHostTask(collector).collect()

        self.assertEqual(fragment["cpu"]["temperature_c"], 55.0)
        self.assertEqual(fragment["gpu"]["source"], "sensor_host")
        self.assertEqual(fragment["power"]["watts"], 88.8)
        self.assertEqual(fragment["disks"][0]["temperature_c"], 40.0)

    def test_collect_returns_empty_when_not_windows(self):
        """确认非 Windows 环境不会请求 SensorHost。"""
        collector = SimpleNamespace(sensor_host=mock.Mock())
        with mock.patch("collectTask.tasks.sensor_host.platform.system", return_value="Linux"):
            fragment = SensorHostTask(collector).collect()
        self.assertEqual(fragment, {})
        collector.sensor_host.snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
