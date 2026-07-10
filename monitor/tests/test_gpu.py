"""验证各平台 GPU 后端的设备发现与使用率计算。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from monitor_core.collectors.gpu import _LinuxIntelGpuBackend


class LinuxIntelGpuBackendTest(unittest.TestCase):
    """验证 Linux Intel i915 PMU 后端。"""

    def test_i915_busy_events_calculate_highest_engine_usage(self):
        """确认多个 i915 引擎按忙碌时间增量返回最高使用率。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            pmu_root = Path(temporary_directory)
            events_directory = pmu_root / "events"
            events_directory.mkdir()
            (pmu_root / "type").write_text("9\n", encoding="ascii")
            (events_directory / "rcs0-busy").write_text("config=0x0\n", encoding="ascii")
            (events_directory / "vcs0-busy").write_text("event=0x2000\n", encoding="ascii")

            with mock.patch.object(
                _LinuxIntelGpuBackend, "_open_perf_event", side_effect=[11, 12],
            ), mock.patch(
                "monitor_core.collectors.gpu.time.monotonic_ns",
                side_effect=[1_000_000_000, 2_000_000_000],
            ), mock.patch(
                "monitor_core.collectors.gpu.os.read",
                side_effect=[
                    (100_000_000).to_bytes(8, "little"),
                    (200_000_000).to_bytes(8, "little"),
                    (350_000_000).to_bytes(8, "little"),
                    (700_000_000).to_bytes(8, "little"),
                ],
            ), mock.patch("monitor_core.collectors.gpu.os.close") as close:
                backend = _LinuxIntelGpuBackend(pmu_root)
                first = backend.sample()
                second = backend.sample()
                backend.close()

        self.assertIsNone(first["percent"])
        self.assertEqual(second["percent"], 50.0)
        self.assertEqual(second["name"], "Intel GPU")
        self.assertEqual(close.call_count, 2)

    def test_missing_i915_events_reports_backend_unavailable(self):
        """确认没有忙碌事件时后端明确报告不可用。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            pmu_root = Path(temporary_directory)
            (pmu_root / "events").mkdir()
            (pmu_root / "type").write_text("9\n", encoding="ascii")

            with self.assertRaisesRegex(OSError, "未发现可用 i915 GPU 忙碌事件"):
                _LinuxIntelGpuBackend(pmu_root)


if __name__ == "__main__":
    unittest.main()
