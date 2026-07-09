"""SensorHost 生命周期和采集转换测试。"""

import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from collectTask.tasks.sensor_host import SensorHostTask


def load_sensor_host_manager():
    """直接加载 SensorHost 模块，避免 win 包初始化引入托盘依赖。"""
    module_path = Path(__file__).resolve().parents[1] / "win" / "sensor_host.py"
    spec = importlib.util.spec_from_file_location("sensor_host_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SensorHostManager


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


class SensorHostManagerPathTest(unittest.TestCase):
    """验证 SensorHost 可执行文件自动发现路径。"""

    def test_resolve_executable_path_finds_monitor_sensorhost_directory(self):
        """确认源码运行时会查找 monitor/sensorhost 目录。"""
        sensor_host_manager = load_sensor_host_manager()
        monitor_directory = Path(__file__).resolve().parents[1]
        expected_path = monitor_directory / "sensorhost" / "OmniWatch.SensorHost.exe"

        with mock.patch.object(sensor_host_manager, "_candidate_base_directories", return_value=[monitor_directory]):
            resolved_path = sensor_host_manager._resolve_executable_path(None)

        self.assertEqual(resolved_path, expected_path)


if __name__ == "__main__":
    unittest.main()
