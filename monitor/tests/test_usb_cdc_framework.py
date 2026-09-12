"""验证 USB CDC 底层读写线程框架。"""

import json
import queue
import threading
import unittest
import time
from unittest import mock
from types import SimpleNamespace

import serial

from pico_client import JsonFrameRejectedError, PicoJsonClient, build_frame, parse_frame
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


class BlockingWriteSerial(ThreadedSerial):
    """模拟 Windows OVERLAPPED 写入等待底层句柄关闭后才返回。"""

    def __init__(self):
        """初始化写入开始通知和关闭解除事件。"""
        super().__init__()
        self.write_started = threading.Event()
        self.write_released = threading.Event()

    def write(self, data):
        """阻塞写入，直到 close() 模拟释放 Windows 串口句柄。"""
        self.write_started.set()
        self.write_released.wait(2.0)
        if not self.is_open:
            raise serial.SerialException("串口句柄已关闭")
        return super().write(data)

    def close(self):
        """关闭串口并解除阻塞写入。"""
        super().close()
        self.write_released.set()


class UsbCdcFrameworkTest(unittest.TestCase):
    """验证 CDC 框架的读写线程和响应分流行为。"""

    def test_snapshot_survives_startup_backpressure(self):
        """JSONB 首片背压超过旧的 400ms 限制后仍可完整发送。"""
        device = JsonAckSerial()
        client = PicoJsonClient()
        client.serial = device
        client.snapshot_chunk_info = {"version": 3, "encoding": "jsonb", "mode": "binary"}
        framework = UsbCdcFramework(
            device, parse_frame, response_callback=client._handle_cdc_response,
            error_callback=client._handle_cdc_error,
        )
        client.transport = framework
        original_write = device.write
        delayed = [False]

        def delayed_write(data):
            """仅在第一次写入时模拟设备冷启动产生的短暂阻塞。"""
            if not delayed[0]:
                delayed[0] = True
                time.sleep(0.55)
            return original_write(data)

        framework.start()
        try:
            with mock.patch.object(device, "write", side_effect=delayed_write):
                client.send({"version": 1})
            self.assertTrue(framework.is_alive)
            self.assertIn(b"PV1:JSONB:", bytes(device.written))
            self.assertEqual({}, client._json_ack_events)
        finally:
            framework.close()

    def test_snapshot_write_uses_ack_window_and_usb_chunk_cap(self):
        """确认 USB 二进制片不超过 4 KiB，且写入等待沿用 ACK 窗口。"""
        class CapturingTransport:
            """记录协议写入预算的最小传输桩。"""

            def __init__(self):
                """初始化最近一次写入等待时长。"""
                self.timeout = None
                self.maximum_packet_size = 0

            def raise_error_if_any(self):
                """模拟后台读写线程没有待转交异常。"""
                return None

            def read_frame(self, label, timeout=0.0):
                """模拟没有待消费的异步响应。"""
                del label, timeout
                return None

            def write_packet(self, packet, label, build_elapsed_ms=0.0, timeout=1.0):
                """记录单帧预算并返回完整写入耗时结构。"""
                del label
                self.timeout = timeout
                self.maximum_packet_size = max(self.maximum_packet_size, len(packet))
                now = time.monotonic()
                return {
                    "build_elapsed_ms": build_elapsed_ms,
                    "send_started": now,
                    "send_finished": now,
                    "send_elapsed_ms": 0.0,
                    "write_elapsed_ms": 0.0,
                    "slowest_write_ms": 0.0,
                    "flush_elapsed_ms": 0.0,
                    "total_written": len(packet),
                    "chunk_count": 1,
                }

        client = PicoJsonClient()
        client.serial = ThreadedSerial()
        client.json_chunk_size = 16384
        client.snapshot_chunk_info = {"version": 3, "encoding": "jsonb", "mode": "binary", "max_payload": 16384}
        transport = CapturingTransport()
        client.transport = transport
        with mock.patch.object(client, "_wait_json_ack"):
            client.send({"version": 1}, ack_timeout=15.0)

        self.assertLessEqual(transport.maximum_packet_size, 4096 + 64)
        self.assertEqual(15.0, transport.timeout)

    def test_expired_queue_job_never_writes(self):
        """排队时间计入预算，过期任务不得继续写入设备。"""
        from usbCdcFramework import _UsbCdcWriteJob
        device = ThreadedSerial()
        framework = UsbCdcFramework(device, parse_frame)
        job = _UsbCdcWriteJob(b"abc", "测试", 0, 0.01)
        job.deadline = time.monotonic() - 1
        with self.assertRaises(serial.SerialTimeoutException):
            framework._perform_write(job)
        self.assertEqual(b"", device.written)

    def test_partial_write_and_timeout_do_not_duplicate_bytes(self):
        """短写按实际偏移续传，超时异常不盲目重发可能已落线的字节。"""
        from usbCdcFramework import _UsbCdcWriteJob
        device = ThreadedSerial()
        framework = UsbCdcFramework(device, parse_frame)
        with mock.patch.object(device, "write", side_effect=[2, 1]) as writer:
            result = framework._perform_write(_UsbCdcWriteJob(b"abc", "测试", 0, 0.2))
            self.assertEqual(3, result.total_written)
            self.assertEqual(b"c", bytes(writer.call_args_list[1].args[0]))
        with mock.patch.object(device, "write", side_effect=serial.SerialTimeoutException("超时")) as writer:
            with self.assertRaises(serial.SerialTimeoutException):
                framework._perform_write(_UsbCdcWriteJob(b"abc", "测试", 0, 0.2))
            self.assertEqual(1, writer.call_count)

    def test_permanent_backpressure_stops_connection(self):
        """持续零写入在统一预算内失败，后台任务被取消且连接失效。"""
        device = ThreadedSerial(zero_writes=100000)
        framework = UsbCdcFramework(device, parse_frame)
        framework.start()
        started = time.monotonic()
        try:
            with self.assertRaises(serial.SerialTimeoutException):
                framework.write_packet(b"abc", "测试", timeout=0.04)
            self.assertLess(time.monotonic() - started, 0.4)
            self.assertFalse(framework.is_alive)
            self.assertEqual(b"", device.written)
        finally:
            framework.close(wait=True)

    def test_close_releases_blocking_write_before_joining_writer(self):
        """关闭框架时应先释放底层句柄，避免阻塞写线程遗留占用 COM 口。"""
        device = BlockingWriteSerial()
        framework = UsbCdcFramework(device, parse_frame)
        framework.start()
        write_result = []

        def write_packet():
            """在后台提交一条长等待写入。"""
            try:
                framework.write_packet(b"abc", "测试", timeout=5.0)
            except Exception as error:
                write_result.append(error)

        writer = threading.Thread(target=write_packet)
        writer.start()
        self.assertTrue(device.write_started.wait(1.0))
        started = time.monotonic()
        framework.close(wait=True)
        writer.join(1.0)

        self.assertLess(time.monotonic() - started, 0.8)
        self.assertFalse(writer.is_alive())
        self.assertTrue(write_result)

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

    def test_framed_write_does_not_wait_on_unbounded_serial_flush(self):
        """完整 PV1 帧不应因 Windows 串口 flush 等待设备消费而卡死。"""
        device = ThreadedSerial()

        def blocking_flush():
            """模拟设备端背压导致 pyserial.flush 长时间等待。"""
            time.sleep(0.5)

        device.flush = blocking_flush
        framework = UsbCdcFramework(device, parse_frame)
        framework.start()
        started = time.monotonic()
        try:
            result = framework.write_packet(b"PV1:JSONZ:test\n", "JSONZ#test", timeout=0.1)
            elapsed = time.monotonic() - started
        finally:
            framework.close(wait=True)

        self.assertLess(elapsed, 0.3)
        self.assertEqual(0.0, result["flush_elapsed_ms"])

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

    def test_frame_error_immediately_wakes_current_ack_waiter(self):
        """设备帧错误应立即结束长 ACK 等待，并保留连接供下一帧重试。"""
        client = PicoJsonClient()
        client.serial = ThreadedSerial()
        client.transport = SimpleNamespace(raise_error_if_any=lambda: None)
        event = client._register_json_ack_waiter(42)

        self.assertTrue(client._handle_cdc_error(("ERR", b"BAD_FRAME_TRAILER")))
        started = time.monotonic()
        with self.assertRaisesRegex(JsonFrameRejectedError, "BAD_FRAME_TRAILER"):
            client._wait_json_ack(42, event, timeout=90.0)

        self.assertLess(time.monotonic() - started, 0.2)
        self.assertTrue(client.is_connected)
        client._remove_json_ack_waiter(42)

    def test_event_callback_receives_device_config_change(self):
        """设备配置事件应由统一读回调实时转交业务层。"""
        client = PicoJsonClient()
        events = []
        client.event_callback = events.append

        client._handle_cdc_response(
            "测试读线程",
            b"PV1:EVENT",
            (
                "EVENT",
                b'configChange:{"key":"lcd_style","value":"thermal_watch"}',
            ),
        )

        self.assertEqual(
            [b'configChange:{"key":"lcd_style","value":"thermal_watch"}'],
            events,
        )

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
