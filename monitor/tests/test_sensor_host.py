"""SensorHost 生命周期和采集转换测试。"""

import unittest
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from collectTask.tasks.win.sensor_host import SensorHostTask
from collectTask.tasks.win.windows_disk_space import WindowsDiskSpaceTask


def load_sensor_host_manager():
    """直接加载 SensorHost 模块，避免 win 包初始化引入托盘依赖。"""
    return load_sensor_host_module().SensorHostManager


def load_sensor_host_module():
    """加载 SensorHost 模块，便于测试模块级常量和依赖。"""
    module_path = Path(__file__).resolve().parents[1] / "win" / "sensor_host.py"
    spec = importlib.util.spec_from_file_location("sensor_host_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            mark_sensor_host_metric_available=mock.Mock(),
            _disk_task_snapshot={"disk": {}, "disks": [], "physical_disks": []},
        )
        collector.sensor_host.snapshot.return_value = {
            "cpu": {"percent": 12.3, "frequency_ghz": 4.2, "temperature_c": 55.0},
            "memory": {
                "physical": {"percent": 67.8, "used_bytes": 600, "available_bytes": 400},
                "virtual": {"percent": 75.0, "used_bytes": 1500, "available_bytes": 500},
            },
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

        fragment = SensorHostTask(collector).collect()

        self.assertEqual(fragment["cpu"]["temperature_c"], 55.0)
        self.assertEqual(fragment["memory"]["total_bytes"], 1000)
        self.assertEqual(fragment["memory"]["used_bytes"], 600)
        self.assertEqual(fragment["gpu"]["source"], "sensor_host")
        self.assertEqual(fragment["power"]["watts"], 88.8)
        self.assertEqual(fragment["disks"][0]["temperature_c"], 40.0)
        collector.mark_sensor_host_metric_available.assert_has_calls([
            mock.call("cpu"),
            mock.call("memory"),
            mock.call("gpu"),
            mock.call("power"),
        ])

    def test_sensor_host_disk_percent_does_not_publish_fake_capacity(self):
        """确认 SensorHost 只有占用百分比时不会伪造容量字节。"""
        collector = SimpleNamespace(
            sensor_host=mock.Mock(),
            histories={"cpu": [], "memory": []},
            history_states={},
            gpu_history=[],
            power_history=[],
            disk_io_histories={},
            mark_sensor_host_metric_available=mock.Mock(),
            _disk_task_snapshot={"disk": {}, "disks": [], "physical_disks": []},
        )
        collector.sensor_host.snapshot.return_value = {
            "disks": [{"name": "HP SSD FX700 1TB", "used_space_percent": 76.6}],
        }

        fragment = SensorHostTask(collector).collect()

        self.assertEqual(fragment["disk"], {"percent": 76.6})
        self.assertNotIn("used_bytes", fragment["disks"][0])
        self.assertNotIn("total_bytes", fragment["disks"][0])
        collector.mark_sensor_host_metric_available.assert_any_call("disk_space_percent")

    def test_cpu_frequency_uses_cores_average_clock_sensor(self):
        """确认 CPU 频率字段缺失时会从 Cores (Average) 时钟传感器补齐。"""
        collector = SimpleNamespace(
            sensor_host=mock.Mock(),
            histories={"cpu": [], "memory": []},
            history_states={},
            gpu_history=[],
            power_history=[],
            mark_sensor_host_metric_available=mock.Mock(),
            _disk_task_snapshot={"disk": {}, "disks": [], "physical_disks": []},
            _cpu_frequency_ghz=mock.Mock(return_value=3.6),
        )
        collector.sensor_host.snapshot.return_value = {
            "cpu": {"percent": 12.3},
            "hardware": [{
                "type": "Cpu",
                "sensors": [{"name": "Cores (Average)", "type": "Clock", "value": 4061, "unit": "MHz"}],
            }],
        }

        fragment = SensorHostTask(collector).collect()

        self.assertEqual(fragment["cpu"]["frequency_ghz"], 4.06)
        collector._cpu_frequency_ghz.assert_not_called()

    def test_cpu_frequency_falls_back_to_legacy_collector(self):
        """确认 SensorHost 传感器也缺失时会降级执行旧 CPU 速度采集。"""
        collector = SimpleNamespace(
            sensor_host=mock.Mock(),
            histories={"cpu": [], "memory": []},
            history_states={},
            gpu_history=[],
            power_history=[],
            mark_sensor_host_metric_available=mock.Mock(),
            _disk_task_snapshot={"disk": {}, "disks": [], "physical_disks": []},
            _cpu_frequency_ghz=mock.Mock(return_value=3.6),
        )
        collector.sensor_host.snapshot.return_value = {"cpu": {"percent": 12.3}, "hardware": []}

        fragment = SensorHostTask(collector).collect()

        self.assertEqual(fragment["cpu"]["frequency_ghz"], 3.6)
        collector._cpu_frequency_ghz.assert_called_once_with()

    def test_task_declares_windows_only_platform(self):
        """确认 SensorHost 任务只通过平台声明参与 Windows 调度。"""
        self.assertTrue(SensorHostTask.supports_current_platform("Windows"))
        self.assertFalse(SensorHostTask.supports_current_platform("Linux"))


class WindowsDiskSpaceTaskTest(unittest.TestCase):
    """验证 Windows 磁盘空间补齐任务。"""

    def test_collect_uses_wmi_total_size_and_sensor_host_percent(self):
        """确认任务会用 WMI 总容量和 SensorHost 占用率计算空间字段。"""
        collector = SimpleNamespace(
            _disk_task_snapshot={
                "disk": {"percent": 76.6},
                "disks": [{"name": "HP SSD FX700 1TB", "percent": 76.6, "health": 1}],
                "physical_disks": [{"name": "HP SSD FX700 1TB", "percent": 76.6, "health": 1}],
            },
            is_sensor_host_metric_available=lambda name: name == "disk_space_percent",
            mark_sensor_host_metric_available=mock.Mock(),
        )

        with mock.patch.object(
            WindowsDiskSpaceTask,
            "_disk_drive_sizes",
            return_value=[{"model": "HP SSD FX700 1TB", "total_bytes": 1000}],
        ):
            fragment = WindowsDiskSpaceTask(collector).collect()

        self.assertEqual(fragment["disk"], {
            "percent": 76.6,
            "used_bytes": 766,
            "total_bytes": 1000,
            "free_bytes": 234,
        })
        self.assertEqual(fragment["disks"][0]["used_bytes"], 766)
        self.assertEqual(fragment["disks"][0]["total_bytes"], 1000)
        self.assertEqual(fragment["disks"][0]["free_bytes"], 234)
        collector.mark_sensor_host_metric_available.assert_called_once_with("disk_capacity_health")


class SensorHostManagerPathTest(unittest.TestCase):
    """验证 SensorHost 可执行文件自动发现路径。"""

    def test_resolve_executable_path_prefers_latest_versioned_sensorhost(self):
        """确认自动发现优先使用 monitor/sensorhost 中版本号最高的可执行文件。"""
        sensor_host_manager = load_sensor_host_manager()
        with tempfile.TemporaryDirectory() as temporary_directory:
            monitor_directory = Path(temporary_directory)
            sensorhost_directory = monitor_directory / "sensorhost"
            sensorhost_directory.mkdir()
            (sensorhost_directory / "OmniWatch.SensorHost.exe").touch()
            (sensorhost_directory / "OmniWatch.SensorHost-v1.0.5.exe").touch()
            expected_path = sensorhost_directory / "OmniWatch.SensorHost-v1.0.10.exe"
            expected_path.touch()

            with mock.patch.object(sensor_host_manager, "_candidate_base_directories", return_value=[monitor_directory]):
                resolved_path = sensor_host_manager._resolve_executable_path(None)

        self.assertEqual(resolved_path, expected_path)


class SensorHostManagerStartupTest(unittest.TestCase):
    """验证 SensorHost 启动预热与进程健康检查。"""

    def _build_manager(self):
        """构造绕过平台依赖的 SensorHost 管理器实例。"""
        sensor_host_module = load_sensor_host_module()
        manager = sensor_host_module.SensorHostManager.__new__(sensor_host_module.SensorHostManager)
        manager.executable_path = Path("OmniWatch.SensorHost.exe")
        manager.pipe_name = sensor_host_module.DEFAULT_PIPE_NAME
        manager.process = None
        manager.job = None
        manager.process_started_at = None
        manager.dependency_unavailable_message = None
        manager.available = True
        manager._unavailable_logged = False
        return sensor_host_module, manager

    def test_snapshot_skips_pipe_request_during_startup_grace(self):
        """确认刚启动的 SensorHost 不会立即连接命名管道。"""
        sensor_host_module, manager = self._build_manager()
        process = mock.Mock()
        process.pid = 1234
        process.poll.return_value = None

        with mock.patch.object(sensor_host_module.subprocess, "Popen", return_value=process), \
                mock.patch.object(manager, "_attach_job_object"), \
                mock.patch.object(manager, "_request") as request:
            snapshot = manager.snapshot()

        self.assertIsNone(snapshot)
        request.assert_not_called()

    def test_snapshot_requests_pipe_after_startup_grace(self):
        """确认 SensorHost 度过预热期后才请求快照。"""
        sensor_host_module, manager = self._build_manager()
        process = mock.Mock()
        process.poll.return_value = None
        manager.process = process
        manager.process_started_at = time_value = 100.0

        with mock.patch.object(sensor_host_module.time, "monotonic", return_value=time_value + 3.0), \
                mock.patch.object(manager, "_request", return_value={"ok": True}) as request:
            snapshot = manager.snapshot()

        self.assertEqual(snapshot, {"ok": True})
        request.assert_called_once_with("snapshot", sensor_host_module.DEFAULT_REQUEST_TIMEOUT_SECONDS)

    def test_snapshot_skips_pipe_request_when_process_exited(self):
        """确认 SensorHost 进程异常退出时不会继续探测命名管道。"""
        sensor_host_module, manager = self._build_manager()
        process = mock.Mock()
        process.poll.side_effect = [None, 1]
        manager.process = process
        manager.process_started_at = 100.0

        with mock.patch.object(sensor_host_module.time, "monotonic", return_value=103.0), \
                mock.patch.object(manager, "_request") as request:
            snapshot = manager.snapshot()

        self.assertIsNone(snapshot)
        request.assert_not_called()
        self.assertIsNone(manager.process)


if __name__ == "__main__":
    unittest.main()
