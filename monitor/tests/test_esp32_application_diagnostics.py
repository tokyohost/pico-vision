"""验证 ESP32-S3 应用错误页和慢样式告警。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[2] / "esp32-s3"
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

from main import Application  # noqa: E402


class ProtocolRecorder:
    """记录固件写出的诊断日志。"""

    def __init__(self):
        """创建空日志列表。"""
        self.messages = []

    def write(self, payload):
        """保存一次字节日志写入。"""
        self.messages.append(payload.decode("utf-8"))


class Esp32ApplicationDiagnosticsTest(unittest.TestCase):
    """覆盖 LCD 错误展示和 style 帧耗时告警。"""

    def test_gc_is_deferred_while_streaming_with_enough_free_memory(self):
        """确认活动数据流不会因固定五秒周期触发 PSRAM 全堆扫描。"""
        application = Application.__new__(Application)
        application._next_gc = 1000
        application._next_clock_render = 3000
        application._monitor_connected = True
        application._renderer = SimpleNamespace(is_rendering=lambda: False)
        with mock.patch(
            "main.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ), mock.patch(
            "main.time.ticks_add",
            side_effect=lambda value, delta: value + delta,
            create=True,
        ), mock.patch(
            "main.gc.mem_free", return_value=7 * 1024 * 1024,
            create=True,
        ), mock.patch("main.gc.collect") as collect:
            collected = application._collect_garbage_if_safe(1200)

        self.assertFalse(collected)
        collect.assert_not_called()
        self.assertGreater(application._next_gc, 1200)

    def test_application_error_is_rendered_on_boot_style(self):
        """确认未处理异常会切换启动样式并同步提交错误信息。"""
        application = Application.__new__(Application)
        calls = []
        application._renderer = SimpleNamespace(
            abort_render=lambda release_snapshot: calls.append(
                ("abort", release_snapshot)
            ),
            set_style=lambda style_name: calls.append(("style", style_name)),
        )

        def show_boot(progress, log, status, flush=False):
            """记录错误页刷新参数。"""
            calls.append(("show", progress, log, status, flush))

        application._show_boot = show_boot
        application.show_application_error(ValueError("样式计算失败"))

        self.assertEqual(calls[0], ("abort", True))
        self.assertEqual(calls[1], ("style", "boot"))
        self.assertEqual(calls[2], ("show", 100, None, "ERROR - CHECK LOG", True))
        self.assertIn("TYPE:ValueError", application._boot_logs)
        self.assertIn("样式计算失败", application._boot_logs)

    def test_style_frame_over_200ms_writes_warning(self):
        """确认 style 计算超过两百毫秒时输出 WARNING 级别日志。"""
        application = Application.__new__(Application)
        application._protocol = ProtocolRecorder()
        application._monitor_connected = False
        application._dev_mode = False
        application._renderer = SimpleNamespace(
            last_profile=lambda: (200001, 1000, 1),
            style_name=lambda: "slow_style",
        )

        application._write_render_profile_if_needed(True)

        self.assertEqual(len(application._protocol.messages), 1)
        self.assertIn(
            (
                "WARNING:STYLE_FRAME_SLOW:STYLE=slow_style:"
                "ELAPSED=201MS:THRESHOLD=200MS"
            ),
            application._protocol.messages[0],
        )

    def test_style_frame_at_200ms_does_not_write_warning(self):
        """确认 style 计算恰好两百毫秒时不输出慢帧告警。"""
        application = Application.__new__(Application)
        application._protocol = ProtocolRecorder()
        application._monitor_connected = False
        application._dev_mode = False
        application._renderer = SimpleNamespace(
            last_profile=lambda: (200000, 1000, 1),
            style_name=lambda: "normal_style",
        )

        application._write_render_profile_if_needed(True)

        self.assertEqual(application._protocol.messages, [])


if __name__ == "__main__":
    unittest.main()
