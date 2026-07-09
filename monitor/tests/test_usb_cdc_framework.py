"""验证 USB CDC 底层读写线程框架。"""

import queue
import threading
import unittest

import serial

from pico_client import build_frame, parse_frame
from usbCdcFramework import UsbCdcFramework


class ThreadedSerial:
    """模拟支持并发读写的 USB CDC 串口。"""

    def __init__(self, responses=None, zero_writes=0):
        """初始化响应队列、写入缓存和零写入次数。"""
        self.port = "TEST"
        self.is_open = True
        self.responses = queue.Queue()
        self.written = bytearray()
        self.flush_count = 0
        self.zero_writes = zero_writes
        self.lock = threading.Lock()
        for response in responses or []:
            self.responses.put(response)

    def write(self, data):
        """模拟 CDC 写入，按需先返回零表示端点暂时背压。"""
        with self.lock:
            if self.zero_writes > 0:
                self.zero_writes -= 1
                return 0
            payload = bytes(data)
            self.written.extend(payload)
            return len(payload)

    def flush(self):
        """记录刷新次数。"""
        self.flush_count += 1

    def readline(self):
        """按超时方式返回 Pico 响应帧。"""
        try:
            return self.responses.get(timeout=0.02)
        except queue.Empty:
            return b""

    def close(self):
        """关闭模拟串口。"""
        self.is_open = False


class UsbCdcFrameworkTest(unittest.TestCase):
    """验证 CDC 框架的读写线程和响应分流行为。"""

    def test_reader_drains_json_ack_and_keeps_command_response(self):
        """确认 JSON ACK 被读线程消费，COMMAND 响应仍可由控制流程读取。"""
        serial_port = ThreadedSerial([
            build_frame("ACK", b"JSON:7"),
            build_frame("COMMAND", b'{"status":"ok","request_id":"cmd"}'),
        ])
        received = []
        framework = UsbCdcFramework(
            serial_port,
            parse_frame,
            response_callback=lambda label, raw, frame: received.append(frame),
        )
        framework.start()
        try:
            frame = framework.read_frame("command", timeout=1.0)
        finally:
            framework.close()

        self.assertEqual(("COMMAND", b'{"status":"ok","request_id":"cmd"}'), frame)
        self.assertEqual(("ACK", b"JSON:7"), received[0])

    def test_writer_retries_zero_length_usb_write(self):
        """确认 CDC 端点短暂返回零时写线程会退避并继续完成整帧。"""
        serial_port = ThreadedSerial(zero_writes=2)
        framework = UsbCdcFramework(serial_port, parse_frame, write_chunk_size=8)
        framework.start()
        try:
            result = framework.write_packet(b"1234567890", "JSONZ#1", timeout=1.0)
        finally:
            framework.close()

        self.assertEqual(b"1234567890", bytes(serial_port.written))
        self.assertEqual(10, result["total_written"])
        self.assertGreaterEqual(result["chunk_count"], 2)

    def test_reader_reports_bad_frame_as_transport_error(self):
        """确认坏帧会被转为后台通信异常，供主循环触发重连。"""
        serial_port = ThreadedSerial([b"PV1:BROKEN\n"])
        framework = UsbCdcFramework(serial_port, parse_frame)
        framework.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "损坏协议帧"):
                for _ in range(20):
                    framework.read_frame("bad", timeout=0.05)
                    framework.raise_error_if_any()
        finally:
            framework.close()


if __name__ == "__main__":
    unittest.main()
