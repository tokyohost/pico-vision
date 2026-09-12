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
from protocol import JsonProtocol
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


class FakeCompleteFrameTransport:
    """模拟 C 层完整帧队列和异步错误通道。"""

    def __init__(self, frames=None, receive_error=None):
        """初始化完整帧、异步错误与写入记录。"""
        self.frames = list(frames or ())
        self.receive_error = receive_error
        self.written = bytearray()
        self.raw_read_count = 0

    def available(self):
        """返回完整帧和异步错误的待读事件数。"""
        return len(self.frames) + (1 if self.receive_error else 0)

    def uses_complete_frame_queue(self):
        """声明当前模拟传输由 C 层提供完整帧。"""
        return True

    def read_frame(self):
        """取出一个模拟完整帧。"""
        return self.frames.pop(0) if self.frames else None

    def read_receive_error(self):
        """取出并清除一个模拟 C 层错误。"""
        error = self.receive_error
        self.receive_error = None
        return error

    def readinto(self, buffer):
        """记录不应发生的原始半包读取。"""
        del buffer
        self.raw_read_count += 1
        raise AssertionError("C 完整帧模式不得读取原始半包")

    def write(self, data):
        """记录协议层写回的帧。"""
        self.written.extend(data)
        return len(data)

    def flush(self):
        """模拟立即完成 CDC 发送刷新。"""
        return None

    def is_open(self):
        """返回模拟 CDC 始终已连接。"""
        return True


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
        cdc_source = (
            repository_root / "micropython/shared/tinyusb/mp_usbd_cdc.c"
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
        self.assertIn("mp_usbd_cdc_data_rx_read_buffered", cdc_header)
        self.assertIn("mp_usbd_cdc_data_tx_write", cdc_header)
        self.assertIn("mp_usbd_cdc_data_connected", cdc_header)
        self.assertIn("mp_usbd_cdc_data_tx_flush", cdc_header)
        self.assertIn("mp_usbd_cdc_data_reset_session", cdc_source)
        self.assertIn("USBD_CDC_DATA_EP_OUT", cdc_source)
        self.assertIn("usbd_edpt_clear_stall", cdc_source)
        self.assertIn("MICROPY_GC_HOOK_LOOP", board_header)
        self.assertIn("mp_usbd_gc_collect_hook", board_header)
        self.assertIn("mp_usbd_gc_collect_hook", (
            repository_root / "micropython/shared/tinyusb/mp_usbd.c"
        ).read_text(encoding="utf-8"))
        self.assertIn('#include "shared/tinyusb/mp_usbd_cdc.h"', cdc_binding)
        self.assertIn('#include "freertos/idf_additions.h"', cdc_binding)
        self.assertIn("extern void mp_usbd_task_lock_enable(void);", cdc_binding)
        self.assertIn("xTaskCreatePinnedToCore", cdc_binding)
        self.assertIn("vTaskDelay(USB_CDC_TASK_DELAY_TICKS);", cdc_binding)
        self.assertNotIn("vTaskDelay(pdMS_TO_TICKS(1));", cdc_binding)
        self.assertIn("usb_cdc_feed_byte_locked", cdc_binding)
        self.assertIn("MP_QSTR_frames_available", cdc_binding)
        self.assertIn("MP_QSTR_read_frame", cdc_binding)
        self.assertIn("MP_QSTR_read_error", cdc_binding)
        self.assertIn("--undefined=tud_descriptor_device_cb", esp32_cmake)
        self.assertIn("--undefined=tud_descriptor_configuration_cb", esp32_cmake)
        self.assertIn("--undefined=tud_descriptor_string_cb", esp32_cmake)

    def test_bootloader_disconnects_tinyusb_before_switching_usb_phy(self):
        """进入 ROM 前必须先断开双 CDC，不能带着活动端点释放 OTG PHY。"""
        repository_root = ESP32_ROOT.parents[1]
        usb_source = (
            repository_root / "micropython/ports/esp32/usb.c"
        ).read_text(encoding="utf-8")
        function_start = usb_source.index("void usb_usj_mode(void)")
        function_source = usb_source[function_start:]

        disconnect_offset = function_source.index("tud_disconnect();")
        clear_offset = function_source.index("tud_cdc_n_write_clear(interface);")
        delay_offset = function_source.index("mp_hal_delay_ms(50);")
        release_offset = function_source.index("usb_del_phy(phy_hdl);")

        self.assertLess(clear_offset, disconnect_offset)
        self.assertLess(disconnect_offset, delay_offset)
        self.assertLess(delay_offset, release_offset)

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

    def test_native_cdc_initialization_failure_falls_back_before_lcd_start(self):
        """C 缓冲或任务初始化失败时应回退控制台，不得阻断 LCD 启动。"""
        backend = types.SimpleNamespace(
            api_version=lambda: 2,
            init=lambda: (_ for _ in ()).throw(RuntimeError("task failed")),
        )
        with mock.patch.dict(sys.modules, {"_usb_cdc_data": backend}):
            with self.assertRaises(dedicated_cdc.DedicatedCdcUnavailable):
                dedicated_cdc.create_dedicated_cdc(1024, 4096)

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

    def test_console_and_native_cdc_report_distinct_binary_capabilities(self):
        """REPL 回退必须禁用 JSONB，原生第二路 CDC 必须保留 JSONB。"""
        fallback = usb_transport.Esp32S3ConsoleStream.__new__(
            usb_transport.Esp32S3ConsoleStream
        )
        backend = types.SimpleNamespace(
            api_version=lambda: 1,
            init=lambda: None,
        )
        native = NativeCdcStream(backend)

        self.assertFalse(fallback.supports_binary_frames())
        self.assertTrue(native.supports_binary_frames())

    def test_native_cdc_reads_only_complete_c_frames(self):
        """新固件应向 Python 暴露 C 层完整帧队列，不再读取半包字节。"""
        frames = [b"PV1:PING:0:0000:\n"]
        backend = types.SimpleNamespace(
            api_version=lambda: 2,
            init=lambda: None,
            frames_available=lambda: len(frames),
            read_frame=lambda: frames.pop(0) if frames else None,
            read_error=lambda: None,
            is_open=lambda: True,
        )
        native = NativeCdcStream(backend)
        transport = UsbCdcTransport(native)

        self.assertTrue(native.uses_complete_frame_queue())
        self.assertTrue(transport.uses_complete_frame_queue())
        self.assertEqual(1, transport.available())
        self.assertEqual(b"PV1:PING:0:0000:\n", transport.read_frame())
        self.assertIsNone(transport.read_receive_error())
        self.assertEqual(0, transport.available())

    def test_protocol_never_reads_raw_bytes_in_complete_frame_mode(self):
        """Python 协议层必须只取 C 层完整帧，不再进入 readinto 半包路径。"""
        stream = FakeCompleteFrameTransport((JsonProtocol._build_frame("PING", b""),))
        protocol = JsonProtocol(stream=stream)
        protocol._write_pong = lambda: protocol._write_frame("PONG", b"{}")

        self.assertIsNone(protocol.poll())

        self.assertEqual(0, stream.raw_read_count)
        self.assertTrue(bytes(stream.written).startswith(b"PV1:PONG:"))

    def test_protocol_reports_c_partial_frame_timeout(self):
        """C 任务清除超时半帧后，Python 应立即向主机返回 FRAME_TIMEOUT。"""
        stream = FakeCompleteFrameTransport(receive_error=b"FRAME_TIMEOUT")
        protocol = JsonProtocol(stream=stream)

        self.assertIsNone(protocol.poll())

        self.assertEqual(0, stream.raw_read_count)
        self.assertIn(b"FRAME_TIMEOUT", stream.written)

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
