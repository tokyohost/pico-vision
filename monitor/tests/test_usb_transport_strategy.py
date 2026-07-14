"""验证开发板 USB 能力策略与 ESP32-S3 内置控制台适配。"""


import sys
import types
import unittest
from unittest import mock
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

import usb_transport
from net.usb_cdc import UsbCdcTransport


class FakePoll:
    """按模拟输入流是否存在数据返回可读事件。"""

    def __init__(self):
        """初始化尚未注册目标的轮询器。"""
        self.target = None

    def register(self, target, event):
        """保存轮询目标并忽略事件掩码。"""
        del event
        self.target = target

    def poll(self, timeout):
        """目标含有待读数据时返回一个模拟事件。"""
        del timeout
        if self.target is not None and self.target.data:
            return ((self.target, 1),)
        return ()


class FakeConsoleInput:
    """提供 ESP32 控制台输入流测试替身。"""

    def __init__(self):
        """初始化空的二进制接收缓冲区。"""
        self.buffer = self
        self.data = bytearray()
        self.read_sizes = []

    def feed(self, data):
        """向模拟控制台加入主机发送的数据。"""
        self.data.extend(data)

    def readinto(self, buffer):
        """把当前待读数据复制到目标缓冲区。"""
        self.read_sizes.append(len(buffer))
        count = min(len(buffer), len(self.data))
        buffer[:count] = self.data[:count]
        del self.data[:count]
        return count


class FakeBatchConsoleInput(FakeConsoleInput):
    """模拟支持定制固件非阻塞批量读取接口的控制台。"""

    def readinto_nonblocking(self, buffer):
        """一次复制当前已有数据，不等待目标缓冲区填满。"""
        return self.readinto(buffer)


class FakeConsoleOutput:
    """记录 ESP32 控制台发送的二进制数据。"""

    def __init__(self):
        """初始化空的发送记录。"""
        self.buffer = self
        self.data = bytearray()
        self.flushed = False

    def write(self, data):
        """保存一段模拟 USB 输出。"""
        self.data.extend(data)
        return len(data)

    def flush(self):
        """记录输出缓冲区已经刷新。"""
        self.flushed = True


class UsbCapabilityStrategyTest(unittest.TestCase):
    """确认 BOARD_MODEL 对应的 USB 能力选择和统一传输行为。"""

    def test_board_models_select_expected_usb_capabilities(self):
        """RP2040 与 ESP32-S3 应选择不同 USB 能力策略。"""
        self.assertEqual(
            "rp2040_usb_device",
            usb_transport.get_usb_capability_strategy("rp2040_usb").name,
        )
        self.assertEqual(
            "rp2040_usb_device",
            usb_transport.get_usb_capability_strategy("rp2040_typec").name,
        )
        self.assertEqual(
            "esp32_s3_builtin_console",
            usb_transport.get_usb_capability_strategy("ESP32-S3").name,
        )

    def test_esp32_builtin_console_works_with_usb_transport(self):
        """ESP32 内置控制台应支持首字节连接、读取和写入。"""
        console_input = FakeConsoleInput()
        console_output = FakeConsoleOutput()
        with mock.patch.object(usb_transport.select, "poll", FakePoll), mock.patch(
            "net.usb_cdc.select.poll",
            FakePoll,
        ):
            stream = usb_transport.create_usb_stream(
                "ESP32-S3",
                wait_for_open=False,
                input_stream=console_input,
                output_stream=console_output,
            )
            transport = UsbCdcTransport(stream)
            self.assertFalse(transport.is_connected())
            console_input.feed(b"PING:PICO_LCD?\n")
            self.assertTrue(transport.is_connected())
            self.assertEqual(1, transport.available())
            buffer = bytearray(32)
            count = transport.readinto(buffer)
            self.assertEqual(b"P", bytes(buffer[:count]))
            self.assertEqual([1], console_input.read_sizes)
            self.assertEqual(4, transport.write(b"PONG"))
            self.assertEqual(b"PONG", bytes(console_output.data))
            transport.flush()
            self.assertFalse(console_output.flushed)
            while transport.available():
                transport.readinto(buffer)
            transport.close()
            self.assertFalse(transport.is_connected())

    def test_esp32_console_reads_64_byte_ping_in_one_nonblocking_batch(self):
        """定制固件应一次批量收完 64 字节握手并立即返回 PONG。"""
        from protocol import JsonProtocol

        console_input = FakeBatchConsoleInput()
        console_output = FakeConsoleOutput()
        with mock.patch.object(usb_transport.select, "poll", FakePoll), mock.patch(
            "net.usb_cdc.select.poll",
            FakePoll,
        ):
            stream = usb_transport.create_usb_stream(
                "ESP32-S3",
                wait_for_open=False,
                input_stream=console_input,
                output_stream=console_output,
            )
            transport = UsbCdcTransport(stream)
            protocol = JsonProtocol(stream=transport)
            ping = JsonProtocol._build_frame("PING", b"").rstrip(b"\n")
            wire_ping = ping + b" " * (63 - len(ping)) + b"\n"
            self.assertEqual(64, len(wire_ping))

            console_input.feed(wire_ping)
            # 桌面测试环境没有 machine 模块，用最小 PONG 替身聚焦验证 USB 收发链。
            with mock.patch.object(
                JsonProtocol,
                "_write_pong",
                lambda instance: instance._write_frame("PONG", b"{}"),
            ):
                self.assertIsNone(protocol.poll())

        self.assertEqual([512], console_input.read_sizes)
        self.assertTrue(bytes(console_output.data).startswith(b"PV1:PONG:"))

    def test_esp32_console_falls_back_to_single_byte_reads(self):
        """标准固件缺少批量接口时应保持严格非阻塞的单字节回退。"""
        console_input = FakeConsoleInput()
        console_input.feed(b"ABC")
        with mock.patch.object(usb_transport.select, "poll", FakePoll):
            stream = usb_transport.create_usb_stream(
                "ESP32-S3",
                wait_for_open=False,
                input_stream=console_input,
                output_stream=FakeConsoleOutput(),
            )
            buffer = bytearray(16)
            self.assertEqual(1, stream.readinto(buffer))

        self.assertEqual(b"A", bytes(buffer[:1]))
        self.assertEqual([1], console_input.read_sizes)

    def test_esp32_console_releases_inactive_session(self):
        """ESP32 USB 会话长期无数据时应释放给其他传输策略。"""
        console_input = FakeConsoleInput()
        with mock.patch.object(usb_transport.select, "poll", FakePoll), mock.patch.object(
            usb_transport,
            "_ticks_ms",
            return_value=100,
        ):
            stream = usb_transport.create_usb_stream(
                "esp32-s3",
                wait_for_open=False,
                input_stream=console_input,
                output_stream=FakeConsoleOutput(),
                session_timeout_ms=5000,
            )
            console_input.feed(b"P")
            self.assertTrue(stream.is_open())
            stream.readinto(bytearray(1))
        with mock.patch.object(usb_transport, "_ticks_ms", return_value=5100):
            self.assertFalse(stream.is_open())

    def test_rp2040_requires_machine_usb_device(self):
        """RP2040 策略缺少 machine.USBDevice 时应返回明确能力错误。"""
        with mock.patch.dict(sys.modules, {"machine": types.SimpleNamespace()}):
            with self.assertRaisesRegex(
                RuntimeError,
                "RP2040_USB_DEVICE_CAPABILITY_UNAVAILABLE",
            ):
                usb_transport.create_usb_stream(
                    "rp2040_usb",
                    wait_for_open=False,
                )

    def test_unknown_board_has_clear_usb_capability_error(self):
        """未知开发板型号不应静默回退到错误的 USB 实现。"""
        with self.assertRaisesRegex(ValueError, "未知开发板 USB 能力"):
            usb_transport.get_usb_capability_strategy("unknown")


if __name__ == "__main__":
    unittest.main()
