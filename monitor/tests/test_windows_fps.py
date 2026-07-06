"""Tests for Windows PresentMon/ETW FPS aggregation and fallback behavior."""

import sys
import unittest
from pathlib import Path
from unittest import mock


MONITOR_ROOT = Path(__file__).resolve().parents[1]
if str(MONITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MONITOR_ROOT))

from win.fps.monitor import FpsMonitor
from win.fps.presentmon import PresentMonBackend


class PresentMonBackendTest(unittest.TestCase):
    def test_counts_foreground_process_busiest_swap_chain(self):
        backend = PresentMonBackend(executable=__file__, window_seconds=1.0, clock=lambda: 10.0)
        header = ["Application", "ProcessID", "SwapChainAddress", "MsBetweenPresents"]
        for index in range(60):
            backend.consume_csv_line(header, "game.exe,42,0x1,16.7", 9.01 + index * 0.016)
        for index in range(20):
            backend.consume_csv_line(header, "overlay.exe,7,0x2,50", 9.01 + index * 0.04)

        with mock.patch("win.fps.presentmon.foreground_process_id", return_value=42):
            snapshot = backend.snapshot()

        self.assertEqual(snapshot["value"], 60.0)
        self.assertEqual(snapshot["process_id"], 42)
        self.assertEqual(snapshot["process_name"], "game.exe")

    def test_ignores_malformed_csv_rows(self):
        backend = PresentMonBackend(executable=__file__)
        self.assertFalse(backend.consume_csv_line(["Application", "ProcessID"], "game.exe,invalid"))
        self.assertIsNone(backend.snapshot())

    def test_counts_chromium_child_process_for_foreground_application(self):
        """验证 Chromium 渲染子进程的帧可归属到前台浏览器应用。"""
        backend = PresentMonBackend(executable=__file__, window_seconds=1.0, clock=lambda: 10.0)
        header = ["Application", "ProcessID", "SwapChainAddress"]
        for index in range(60):
            backend.consume_csv_line(header, "chrome.exe,33916,0x1", 9.01 + index * 0.016)

        with mock.patch("win.fps.presentmon.foreground_process_id", return_value=10040), mock.patch(
            "win.fps.presentmon.related_process_ids", return_value={10040}
        ), mock.patch("win.fps.presentmon.process_name", return_value="chrome.exe"):
            snapshot = backend.snapshot()

        self.assertEqual(snapshot["value"], 60.0)
        self.assertEqual(snapshot["process_id"], 33916)
        self.assertEqual(snapshot["process_name"], "chrome.exe")

    def test_command_disables_expensive_metrics_and_file_output(self):
        command = PresentMonBackend.command(Path("PresentMon.exe"))
        self.assertIn("--output_stdout", command)
        self.assertIn("--no_track_gpu", command)
        self.assertIn("--no_track_input", command)
        self.assertNotIn("--output_file", command)


class FpsMonitorTest(unittest.TestCase):
    def test_primary_backend_wins_and_history_is_published(self):
        class Backend:
            def __init__(self, value, source):
                self.value, self.source = value, source

            def start(self):
                pass

            def close(self):
                pass

            def snapshot(self):
                return {"value": self.value, "source": self.source, "process_id": 1, "process_name": "game.exe"}

        with mock.patch("win.fps.monitor.platform.system", return_value="Windows"):
            monitor = FpsMonitor(history_length=4, backend_factories=(
                lambda: Backend(60, "presentmon_etw"),
                lambda: Backend(61, "amd_adlx"),
            ))
        snapshot = monitor.snapshot(now=10.0)

        self.assertEqual(snapshot["value"], 60.0)
        self.assertEqual(snapshot["source"], "presentmon_etw")
        self.assertEqual(snapshot["history"], [0, 0, 0, 60.0])

    def test_adlx_is_used_when_presentmon_has_no_current_sample(self):
        class EmptyBackend:
            def start(self): pass
            def close(self): pass
            def snapshot(self): return None

        class AdlxBackend:
            def start(self): pass
            def close(self): pass
            def snapshot(self):
                return {"value": 75, "source": "amd_adlx", "process_id": None, "process_name": ""}

        with mock.patch("win.fps.monitor.platform.system", return_value="Windows"):
            monitor = FpsMonitor(history_length=4, backend_factories=(EmptyBackend, AdlxBackend))
        self.assertEqual(monitor.snapshot(now=10.0)["source"], "amd_adlx")


if __name__ == "__main__":
    unittest.main()
