"""验证 PV1 原生解析能力检测与 Python 回退行为。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
sys.path.insert(0, str(PICO_ROOT))

import protocol  # noqa: E402
import protocolC  # noqa: E402


class PartialWriteStream:
    """模拟 USB CDC 缓冲区每次只能接收部分数据的输出流。"""

    def __init__(self, maximum_write_size):
        """初始化单次写入上限和已接收数据缓冲区。"""
        self.maximum_write_size = maximum_write_size
        self.received = bytearray()
        self.flush_count = 0

    def write(self, data):
        """仅接收指定上限的数据并返回实际写入字节数。"""
        written = min(len(data), self.maximum_write_size)
        self.received.extend(data[:written])
        return written

    def flush(self):
        """记录刷新次数以验证每个 USB 短块都会及时提交。"""
        self.flush_count += 1


class BackpressureStream(PartialWriteStream):
    """模拟 USB CDC 首次写入因缓冲区已满而返回零。"""

    def __init__(self, maximum_write_size):
        """初始化部分写入流并记录是否已经产生过背压。"""
        super().__init__(maximum_write_size)
        self.backpressure_returned = False

    def write(self, data):
        """首次调用返回零，后续调用恢复正常部分写入。"""
        if not self.backpressure_returned:
            self.backpressure_returned = True
            return 0
        return super().write(data)


class ProtocolBackendTest(unittest.TestCase):
    """验证原生协议后端只在接口完整兼容时启用。"""

    def test_python_fallback_without_native_module(self):
        """确认 UF2 缺少原生模块时仍使用原有 Python 解析器。"""
        frame = protocol.JsonProtocol._build_frame("JSONZ", b"eJwDAAAAAAE=").rstrip(b"\n")
        with mock.patch.object(protocolC, "_native_protocol", None):
            message_type, payload = protocol.JsonProtocol._parse_frame(frame)
        self.assertEqual("JSONZ", message_type)
        self.assertEqual(b"eJwDAAAAAAE=", payload)

    def test_protocol_backend_reports_python_fallback(self):
        """确认缺少原生协议模块时诊断信息报告 Python 后端。"""
        with mock.patch.object(protocolC, "_native_protocol", None):
            self.assertEqual("PYTHON", protocol.JsonProtocol.protocol_backend())

    def test_native_parser_when_api_is_compatible(self):
        """确认接口版本匹配时把帧解析交给固件原生模块。"""
        native_module = mock.Mock()
        native_module.api_version.return_value = protocolC.NATIVE_PROTOCOL_API_VERSION
        native_module.parse_frame.return_value = ("PING", b"")
        with mock.patch.object(protocolC, "_native_protocol", native_module):
            result = protocol.JsonProtocol._parse_frame(b"native-frame")
        self.assertEqual(("PING", b""), result)
        native_module.parse_frame.assert_called_once_with(
            b"native-frame", protocol.MAX_JSON_SIZE
        )

    def test_protocol_backend_reports_native_c(self):
        """确认原生协议接口兼容时诊断信息报告 C 后端。"""
        native_module = mock.Mock()
        native_module.api_version.return_value = protocolC.NATIVE_PROTOCOL_API_VERSION
        native_module.parse_frame.return_value = ("PING", b"")
        with mock.patch.object(protocolC, "_native_protocol", native_module):
            self.assertEqual("C", protocol.JsonProtocol.protocol_backend())

    def test_python_fallback_for_incompatible_api(self):
        """确认原生接口版本不匹配时不会调用其解析函数。"""
        frame = protocol.JsonProtocol._build_frame("PING", b"").rstrip(b"\n")
        native_module = mock.Mock()
        native_module.api_version.return_value = 999
        with mock.patch.object(protocolC, "_native_protocol", native_module):
            self.assertEqual(("PING", b""), protocol.JsonProtocol._parse_frame(frame))
        native_module.parse_frame.assert_not_called()

    def test_write_raw_retries_partial_usb_writes(self):
        """确认较长 PONG 帧在 USB 部分写入时仍能完整发送。"""
        stream = PartialWriteStream(64)
        instance = protocol.JsonProtocol.__new__(protocol.JsonProtocol)
        instance._output = stream
        payload = b'{"device_name":"PICO_LCD","styles":[]}' * 40
        frame = protocol.JsonProtocol._build_frame("PONG", payload)

        instance._write_raw(frame)

        self.assertEqual(frame, bytes(stream.received))
        self.assertGreater(stream.flush_count, 1)

    @mock.patch.object(protocol.time, "sleep")
    def test_write_raw_retries_usb_backpressure(self, sleep):
        """确认 USB CDC 暂时返回零时会退避并继续发送完整 PONG。"""
        stream = BackpressureStream(63)
        instance = protocol.JsonProtocol.__new__(protocol.JsonProtocol)
        instance._output = stream
        frame = protocol.JsonProtocol._build_frame("PONG", b'{"device_name":"PICO_LCD"}')

        instance._write_raw(frame)

        self.assertEqual(frame, bytes(stream.received))
        sleep.assert_called()


if __name__ == "__main__":
    unittest.main()
