"""验证 USB 吞吐诊断的依据、提示阈值和串口发送路径集成。"""

import time
import unittest
from types import SimpleNamespace
from unittest import mock

from pico_client import PicoJsonClient
from usb_transfer_diagnostics import UsbTransferDiagnostics


class ConfigurationCountingSerial:
    """记录串口配置次数和完整写入字节，检查直接发送路径的控制线行为。"""

    def __init__(self):
        """初始化打开状态、固定写入超时和写入缓存。"""
        self.port = "TEST"
        self.is_open = True
        self.written = bytearray()
        self.configuration_count = 0
        self._write_timeout = 1.0

    @property
    def write_timeout(self):
        """读取当前固定超时。"""
        return self._write_timeout

    @write_timeout.setter
    def write_timeout(self, value):
        """记录可能触发 USB 控制请求的串口配置赋值。"""
        self._write_timeout = value
        self.configuration_count += 1

    def write(self, data):
        """接受完整写入字节，供发送结果对照。"""
        self.written.extend(data)
        return len(data)

    def flush(self):
        """提供无需额外等待的测试流刷新接口。"""
        return None

    def close(self):
        """关闭测试串口。"""
        self.is_open = False


class UsbTransferDiagnosticsTest(unittest.TestCase):
    """验证持续异常才提示换线，同时正确区分主机吞吐和线材物理速率。"""

    def setUp(self):
        """创建独立诊断器并固定时钟，避免真实等待影响时间窗口断言。"""
        self.diagnostics = UsbTransferDiagnostics()
        self.clock = mock.patch("usb_transfer_diagnostics.time.monotonic", return_value=0.0).start()
        self.addCleanup(mock.patch.stopall)

    def write(self, elapsed_ms=1000, written=2048):
        """记录指定字节和耗时的主机写入样本。"""
        self.diagnostics.record_write("COM78", "JSONB#1", {
            "send_elapsed_ms": elapsed_ms, "total_written": written, "slowest_write_ms": elapsed_ms / 2,
        })

    def test_three_slow_writes_provide_rate_and_cable_hint(self):
        """连续三次低速写入给出吞吐数值及换线建议，不直接认定线材故障。"""
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            for _ in range(3):
                self.write()
        text = "\n".join(logs.output)
        self.assertIn("主机有效写入 2.00 KiB/s", text)
        self.assertIn("尝试更换可靠的数据线", text)
        self.assertIn("不能判定数据线故障", text)
        self.assertEqual(1, len(logs.output))

    def test_healthy_write_breaks_slow_write_streak(self):
        """短暂启动延迟或孤立慢写恢复后不会积累为换线告警。"""
        with self.assertNoLogs("pico-monitor.serial", level="WARNING"):
            self.write()
            self.write()
            self.write(elapsed_ms=10)
            self.write()
            self.write()

    def test_old_slow_writes_expire_from_window(self):
        """跨过三十秒窗口的慢写不会触发持续低速提示。"""
        with self.assertNoLogs("pico-monitor.serial", level="WARNING"):
            for instant in (0, 31, 62):
                self.clock.return_value = instant
                self.write()

    def test_small_frames_and_zero_durations_do_not_trigger_slow_hint(self):
        """小命令帧和不足以计算吞吐的耗时不会误导用户更换数据线。"""
        with self.assertNoLogs("pico-monitor.serial", level="WARNING"):
            for _ in range(4):
                self.write(written=64)
                self.write(elapsed_ms=0)

    def test_frame_timeouts_include_fast_write_evidence_and_rate_limit_hint(self):
        """设备连续超时附带最近快速写入证据，排查提示遵守一分钟冷却。"""
        self.write(elapsed_ms=100)
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            for instant in (1, 2, 3, 4, 5):
                self.clock.return_value = instant
                self.diagnostics.record_frame_timeout("COM78")
        text = "\n".join(logs.output)
        self.assertIn("FRAME_TIMEOUT=3", text)
        self.assertIn("20.00 KiB/s", text)
        self.assertIn("主机写入完成不代表设备收到完整帧", text)
        self.assertEqual(1, text.count("[USB 链路排查]"))

    def test_stale_write_metrics_are_not_attached_to_timeout(self):
        """超过三十秒的写入样本不会用作当前帧超时的链路证据。"""
        self.write()
        self.clock.return_value = 31
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            self.diagnostics.record_frame_timeout("COM78")
        self.assertIn("没有已完成写入的吞吐记录", "\n".join(logs.output))

    def test_reset_clears_timeout_counts_and_latest_write(self):
        """新连接不能继承旧连接的超时次数及吞吐数值。"""
        self.write()
        with self.assertLogs("pico-monitor.serial", level="WARNING"):
            self.diagnostics.record_frame_timeout("COM78")
            self.diagnostics.record_frame_timeout("COM78")
        self.diagnostics.reset()
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            self.diagnostics.record_frame_timeout("COM79")
        text = "\n".join(logs.output)
        self.assertIn("FRAME_TIMEOUT=1", text)
        self.assertNotIn("[USB 链路排查]", text)
        self.assertNotIn("JSONB#1", text)


class UsbTransferDiagnosticsIntegrationTest(unittest.TestCase):
    """验证 USB 的两种发送路径及错误处理都正确接入诊断。"""

    def test_direct_usb_write_with_deadline_does_not_reconfigure_port(self):
        """有截止时间的直接 USB 写入仍保持固定串口配置，并完整传输物理帧。"""
        client = PicoJsonClient()
        client.serial = ConfigurationCountingSerial()
        packet = b"x" * 2047 + b"\n"

        timing = client._write_packet(packet, "JSONB#1", deadline=time.monotonic() + 5)

        self.assertEqual(packet, bytes(client.serial.written))
        self.assertEqual(0, client.serial.configuration_count)
        self.assertEqual(2048, timing["total_written"])
        self.assertIsNotNone(client._usb_transfer_diagnostics._last_write)

    def test_framework_write_records_completed_frame_throughput(self):
        """CDC 后台写线程的完成结果进入诊断器，速率以该次实际写入字节计算。"""
        client = PicoJsonClient()
        client.serial = ConfigurationCountingSerial()
        client.transport = SimpleNamespace(raise_error_if_any=lambda: None, write_packet=mock.Mock(return_value={
            "send_elapsed_ms": 100, "write_elapsed_ms": 90, "slowest_write_ms": 50,
            "flush_elapsed_ms": 0, "total_written": 2048, "chunk_count": 5,
        }))
        client._write_packet(b"x" * 2047 + b"\n", "JSONB#2")
        self.assertEqual("JSONB#2", client._usb_transfer_diagnostics._last_write[1])

    def test_repeated_device_frame_timeouts_provide_usb_hint(self):
        """实际 ERR 处理路径在设备连续报告 FRAME_TIMEOUT 时输出排查提示。"""
        client = PicoJsonClient()
        client.serial = ConfigurationCountingSerial()
        client.firmware_version = "2.3.83-build3"
        client.sdk_version = "v1.0.76-fnProcotolV1"
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            for _ in range(3):
                self.assertTrue(client._handle_cdc_error(("ERR", b"FRAME_TIMEOUT")))
        self.assertIn("尝试更换可靠的数据线", "\n".join(logs.output))
        self.assertIn("固件=2.3.83-build3，SDK=v1.0.76-fnProcotolV1", "\n".join(logs.output))

    def test_websocket_frame_timeout_never_suggests_usb_cable(self):
        """WebSocket 的协议超时不输出 USB 线材排查提示。"""
        client = PicoJsonClient(websocket_url="ws://127.0.0.1:8765/pv1")
        client.serial = ConfigurationCountingSerial()
        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            for _ in range(3):
                client._handle_cdc_error(("ERR", b"FRAME_TIMEOUT"))
        self.assertNotIn("[USB", "\n".join(logs.output))

    def test_close_discards_old_usb_diagnostics(self):
        """关闭客户端时立即清除旧设备的慢写证据。"""
        client = PicoJsonClient()
        client.serial = ConfigurationCountingSerial()
        client._write_packet(b"x" * 2047 + b"\n", "JSONB#1")
        client.close()
        self.assertIsNone(client._usb_transfer_diagnostics._last_write)


if __name__ == "__main__":
    unittest.main()
