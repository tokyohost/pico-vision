"""验证固件内置双 CDC 数据流及控制台能力回退。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

import usb_transport
from net.usb_cdc import UsbCdcTransport
from usb import dedicated_cdc
from usb.buffer_policy import normalize_rx_buffer_size
from usb.native_cdc import NativeCdcStream


class FakePoll:
    """根据模拟流的待读数据返回非阻塞可读事件。"""

    def __init__(self):
        """初始化尚未注册目标的轮询器。"""
        self.target = None

    def register(self, target, event):
        """保存轮询目标并忽略桌面测试无需使用的事件掩码。"""
        del event
        self.target = target

    def poll(self, timeout):
        """目标存在待读数据时返回一个模拟可读事件。"""
        del timeout
        if self.target is not None and self.target.data:
            return ((self.target, 1),)
        return ()


class FakeStream:
    """模拟可切换连接状态的非阻塞 USB 双工数据流。"""

    def __init__(self, opened=False):
        """初始化连接状态及收发数据记录。"""
        self.opened = opened
        self.data = bytearray()
        self.written = bytearray()

    def is_open(self):
        """返回测试指定的主机连接状态。"""
        return self.opened

    def readinto(self, buffer):
        """把当前待读数据复制到目标缓冲区。"""
        count = min(len(buffer), len(self.data))
        buffer[:count] = self.data[:count]
        del self.data[:count]
        return count

    def any(self):
        """返回模拟接收缓冲区当前待读字节数。"""
        return len(self.data)

    def write(self, data):
        """记录通过当前模拟流发送的数据。"""
        self.written.extend(data)
        return len(data)

    def flush(self):
        """模拟立即完成的 USB 刷新操作。"""
        return None


class FakeConsoleInput(FakeStream):
    """提供带 buffer 属性的标准输入测试替身。"""

    def __init__(self):
        """初始化空控制台输入及二进制流别名。"""
        super().__init__(opened=False)
        self.buffer = self


class FakeConsoleOutput(FakeStream):
    """提供带 buffer 属性的标准输出测试替身。"""

    def __init__(self):
        """初始化空控制台输出及二进制流别名。"""
        super().__init__(opened=True)
        self.buffer = self


class UsbTransportTest(unittest.TestCase):
    """确认 ESP32-S3 使用固件原生 CDC，并保留能力回退路径。"""

    def test_firmware_uses_two_builtin_tinyusb_cdc_instances(self):
        """板级固件必须启用第二路 CDC 及独立的接口和端点。"""
        repository_root = ESP32_ROOT.parents[1]
        board_header = (
            repository_root
            / "micropython/ports/esp32/boards/ESP32_GENERIC_S3/mpconfigboard.h"
        ).read_text(encoding="utf-8")
        tinyusb_config = (
            repository_root / "micropython/shared/tinyusb/tusb_config.h"
        ).read_text(encoding="utf-8")
        descriptor = (
            repository_root / "micropython/shared/tinyusb/mp_usbd_descriptor.c"
        ).read_text(encoding="utf-8")
        cdc_header = (
            repository_root / "micropython/shared/tinyusb/mp_usbd_cdc.h"
        ).read_text(encoding="utf-8")
        cdc_binding = (
            repository_root
            / "micropython/ports/esp32/usermod/fn_usb_cdc/mod_usb_cdc_data.c"
        ).read_text(encoding="utf-8")
        esp32_cmake = (
            repository_root / "micropython/ports/esp32/esp32_common.cmake"
        ).read_text(encoding="utf-8")

        self.assertIn("MICROPY_HW_USB_CDC_DATA             (1)", board_header)
        self.assertIn("MICROPY_HW_USB_CDC_DATA_RX_BUFSIZE  (32768)", board_header)
        self.assertIn("MICROPY_HW_ENABLE_USB_RUNTIME_DEVICE (0)", board_header)
        self.assertIn("CFG_TUD_CDC             (1 + MICROPY_HW_USB_CDC_DATA)", tinyusb_config)
        self.assertIn("USBD_CDC_DATA_EP_OUT (0x04)", tinyusb_config)
        self.assertIn("USBD_CDC_DATA_EP_IN (0x84)", tinyusb_config)
        self.assertIn("TUD_CDC_DESCRIPTOR(USBD_ITF_CDC_DATA", descriptor)
        self.assertIn("mp_usbd_cdc_data_rx_configure", cdc_header)
        self.assertIn("mp_usbd_cdc_data_rx_any", cdc_header)
        self.assertIn("mp_usbd_cdc_data_rx_read", cdc_header)
        self.assertIn("mp_usbd_cdc_data_tx_write", cdc_header)
        self.assertIn("mp_usbd_cdc_data_connected", cdc_header)
        self.assertIn("mp_usbd_cdc_data_tx_flush", cdc_header)
        self.assertIn('#include "shared/tinyusb/mp_usbd_cdc.h"', cdc_binding)
        self.assertIn("--undefined=tud_descriptor_device_cb", esp32_cmake)
        self.assertIn("--undefined=tud_descriptor_configuration_cb", esp32_cmake)
        self.assertIn("--undefined=tud_descriptor_string_cb", esp32_cmake)

    def test_dedicated_cdc_uses_firmware_native_backend(self):
        """独立数据通道必须使用固件内置 CDC，不能运行期重配 USB。"""
        initialized = []
        backend = types.SimpleNamespace(
            api_version=lambda: 1,
            init=lambda: initialized.append(True),
            any=lambda: 0,
            readinto=lambda buffer: 0,
            write=lambda data: len(data),
            flush=lambda: None,
            is_open=lambda: True,
        )
        with mock.patch.dict(sys.modules, {"_usb_cdc_data": backend}):
            stream = dedicated_cdc.create_dedicated_cdc(1024, 4096)

        self.assertIsInstance(stream, NativeCdcStream)
        self.assertTrue(stream.is_open())
        self.assertEqual(initialized, [True])

    def test_create_usb_stream_returns_raw_dedicated_cdc(self):
        """独立 CDC 创建成功后必须直接交给现有 USB 传输策略。"""
        dedicated = FakeStream(opened=True)
        fallback = FakeStream(opened=True)
        with mock.patch.object(
            usb_transport,
            "Esp32S3ConsoleStream",
            return_value=fallback,
        ), mock.patch.object(
            usb_transport,
            "create_dedicated_cdc",
            return_value=dedicated,
        ):
            stream = usb_transport.create_usb_stream()

        self.assertIs(dedicated, stream)

    def test_receive_buffer_holds_two_maximum_frames(self):
        """独立 CDC 接收队列必须能覆盖业务阻塞期间的双帧突发。"""
        self.assertEqual(32768, normalize_rx_buffer_size(4096, 16384))
        self.assertEqual(32896, normalize_rx_buffer_size(4096, 16384 + 64))

    def test_transport_reports_exact_readable_bytes(self):
        """传输层应直接返回 CDC 缓冲区的可读字节数。"""
        stream = FakeStream(opened=True)
        stream.data.extend(b"x" * 3904)
        with mock.patch("net.usb_cdc.select.poll", FakePoll):
            transport = UsbCdcTransport(stream)
        self.assertEqual(3904, transport.available())

    def test_explicit_console_stream_keeps_legacy_behavior(self):
        """显式传入控制台流时不得在桌面环境尝试注册运行时 USB。"""
        console_input = FakeConsoleInput()
        console_output = FakeConsoleOutput()
        console_input.data.extend(b"P")
        with mock.patch("usb.console.select.poll", FakePoll), mock.patch.object(
            usb_transport,
            "create_dedicated_cdc",
        ) as create_cdc:
            stream = usb_transport.create_usb_stream(
                input_stream=console_input,
                output_stream=console_output,
            )
            self.assertTrue(stream.is_open())
            self.assertEqual(1, stream.readinto(bytearray(8)))

        create_cdc.assert_not_called()

if __name__ == "__main__":
    unittest.main()
