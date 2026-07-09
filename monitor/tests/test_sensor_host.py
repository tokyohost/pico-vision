"""SensorHost 生命周期和采集转换测试。"""

import unittest
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from collectTask.tasks.sensor_host import SensorHostTask


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
            "memory": {"percent": 67.8, "used_bytes": 600, "available_bytes": 400},
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
        self.assertEqual(fragment["memory"]["total_bytes"], 1000)
        self.assertEqual(fragment["gpu"]["source"], "sensor_host")
        self.assertEqual(fragment["power"]["watts"], 88.8)
        self.assertEqual(fragment["disks"][0]["temperature_c"], 40.0)
        collector.mark_sensor_host_metric_available.assert_has_calls([
            mock.call("cpu"),
            mock.call("memory"),
            mock.call("gpu"),
            mock.call("power"),
        ])

    def test_collect_returns_empty_when_not_windows(self):
        """确认非 Windows 环境不会请求 SensorHost。"""
        collector = SimpleNamespace(sensor_host=mock.Mock())
        with mock.patch("collectTask.tasks.sensor_host.platform.system", return_value="Linux"):
            fragment = SensorHostTask(collector).collect()
        self.assertEqual(fragment, {})
        collector.sensor_host.snapshot.assert_not_called()


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
