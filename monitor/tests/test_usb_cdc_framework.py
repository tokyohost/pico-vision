"""验证 USB CDC 底层读写线程框架。"""

import json
import queue
import threading
import unittest
from types import SimpleNamespace

import serial

from pico_client import PicoJsonClient, build_frame, parse_frame
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


class JsonAckSerial(ThreadedSerial):
    """模拟在完整快照写入后由独立读取通道返回 JSON ACK 的设备。"""

    def write(self, data):
        """记录写入内容，并在帧末尾到达时异步提供请求一的 ACK。"""
        written = super().write(data)
        if bytes(data[:written]).endswith(b"\n"):
            self.responses.put(build_frame("ACK", b"JSON:1"))
        return written


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

    def test_client_waiter_is_woken_by_cdc_reader_ack(self):
        """确认后台 CDC 读线程收到 ACK 后能够唤醒快照发送线程。"""
        serial_port = JsonAckSerial()
        client = PicoJsonClient()
        client.serial = serial_port
        framework = UsbCdcFramework(
            serial_port,
            parse_frame,
            response_callback=client._handle_cdc_response,
            error_callback=client._handle_cdc_error,
        )
        client.transport = framework
        framework.start()
        try:
            client.send({"version": 1}, wait_ack=True, ack_timeout=1.0)
        finally:
            framework.close()

        self.assertIn(b"PV1:JSONZ:", bytes(serial_port.written))

    def test_event_callback_receives_device_style_change(self):
        """设备样式事件应由统一读回调实时转交业务层。"""
        client = PicoJsonClient()
        events = []
        client.event_callback = events.append

        client._handle_cdc_response(
            "测试读线程",
            b"PV1:EVENT",
            ("EVENT", b"styleChange:thermal_watch"),
        )

        self.assertEqual([b"styleChange:thermal_watch"], events)

    def test_handshake_splits_full_usb_endpoint_packet(self):
        """确认 64 字节 PING 拆成短包发送，避免 CDC 设备端一直等待后续数据。"""
        pong = build_frame("PONG", json.dumps({
            "board_model": "rp2040_usb",
            "lcd_device_type": "st7789",
        }).encode("utf-8"))
        serial_port = ThreadedSerial([pong])
        writes = []
        original_write = serial_port.write

        def record_write(data):
            """记录每次物理写入长度，并复用串口模拟器保存字节。"""
            writes.append(len(data))
            return original_write(data)

        serial_port.write = record_write
        client = PicoJsonClient(probe_interval=0)

        self.assertTrue(client._handshake(serial_port))
        self.assertEqual([63, 1], writes)
        self.assertEqual(2, serial_port.flush_count)

    def test_esp32_data_cdc_is_ranked_before_repl(self):
        """确认自动发现优先探测 FN Vision Data/MI_02，而不是 REPL/MI_00。"""
        repl = SimpleNamespace(
            device="COM7",
            description="USB 串行设备",
            interface="MicroPython REPL",
            hwid="USB VID:PID=303A:4002 MI_00",
            location="1-2:x.0",
            vid=0x303A,
        )
        data = SimpleNamespace(
            device="COM8",
            description="USB 串行设备",
            interface="FN Vision Data",
            hwid="USB VID:PID=303A:4002 MI_02",
            location="1-2:x.2",
            vid=0x303A,
        )

        ordered = sorted([repl, data], key=PicoJsonClient._serial_port_priority)

        self.assertEqual(["COM8", "COM7"], [item.device for item in ordered])
        self.assertTrue(PicoJsonClient._is_probable_repl_port(repl))
        self.assertFalse(PicoJsonClient._is_probable_repl_port(data))
        self.assertTrue(PicoJsonClient._is_espressif_composite([repl, data]))


if __name__ == "__main__":
    unittest.main()
