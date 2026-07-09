#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""验证系统快照结构和 Pico 串口协议的核心行为。"""


import json
import io
import os
import tempfile
import threading
import unittest
import zlib
import base64
import serial
from unittest import mock
from types import SimpleNamespace

from pico_client import PING_COMMAND, REBOOT_COMMAND, PicoJsonClient, build_frame, parse_frame
from pico_monitor import (
    MonitorService,
    create_argument_parser,
    format_pico_information,
    load_monitor_config,
    log_monitor_version,
    main,
    parse_monitor_arguments,
    show_pico_information,
    validate_arguments,
)
from system_monitor import PowerMonitor, SystemInformationCollector
from monitor_core.console import _stop_log_listener, configure_logging


class FakeSerial:
    """模拟能够确认 JSON 数据的 Pico 串口设备。"""

    def __init__(self):
        """初始化写入缓存和打开状态。"""
        self.is_open = True
        self.port = "TEST"
        self.written = bytearray()
        self.write_calls = 0
        self.reset_input_calls = 0
        self.reset_output_calls = 0

    def write(self, data):
        """记录主机写入的协议字节。"""
        self.write_calls += 1
        self.written.extend(data)
        return len(data)

    def flush(self):
        """模拟立即完成串口发送。"""

    def reset_input_buffer(self):
        self.reset_input_calls += 1

    def reset_output_buffer(self):
        self.reset_output_calls += 1

    def readline(self):
        """返回 Pico JSON 接收确认。"""
        return build_frame("ACK", b"JSON")

    def close(self):
        """将模拟串口切换为关闭状态。"""
        self.is_open = False


class RebootSerial(FakeSerial):
    """模拟确认软重启命令的 Pico。"""

    def readline(self):
        return build_frame("COMMAND", json.dumps({
            "status": "ok",
            "command": "reboot",
            "request_id": "reboot",
        }).encode("utf-8"))


class BadJsonSerial(FakeSerial):
    """模拟 Pico 拒绝单个损坏 JSON 数据帧的串口设备。"""

    def readline(self):
        """返回可恢复的 JSON 解析错误。"""
        return build_frame("ERR", b"BAD_JSON")


class DetailedBadJsonSerial(FakeSerial):
    """模拟 Pico 返回带内存诊断详情的 JSON 解析错误。"""

    def readline(self):
        """返回可恢复的 JSONZ 解压内存错误。"""
        return build_frame(
            "ERR",
            b"BAD_JSON:MEMORY_ZLIB:MemoryError:memory allocation failed",
        )



class ProtocolTimingBeforeAckSerial(FakeSerial):
    """模拟 Pico 先返回 JSONZ 解析耗时事件再返回确认帧。"""

    def __init__(self):
        """准备按顺序返回的协议帧列表。"""
        super().__init__()
        self.responses = [
            build_frame("EVENT", b"PROTOCOL_TIMING:TYPE=JSONZ:BYTES=1919:JSON_BYTES=2999"),
            build_frame("ACK", b"JSON"),
        ]

    def readline(self):
        """返回下一条 Pico 响应帧。"""
        return self.responses.pop(0) if self.responses else b""


class QueuedResponseSerial(FakeSerial):
    """模拟发送前已经缓存了有限响应帧的 Pico 串口设备。"""

    def __init__(self, responses):
        """保存待读取响应，用 in_waiting 触发异步响应清理。"""
        super().__init__()
        self.responses = list(responses)

    @property
    def in_waiting(self):
        """返回仍待消费的缓存响应数量。"""
        return len(self.responses)

    def readline(self):
        """按顺序返回缓存响应。"""
        return self.responses.pop(0) if self.responses else b""

class FatalMemorySerial(FakeSerial):
    """模拟 Pico 堆内存不足并即将自动重启。"""

    def readline(self):
        return build_frame(
            "EVENT",
            b"FATAL:MemoryError:memory allocation failed, allocating 25601 bytes",
        )


class FatalCanvasCapacitySerial(FakeSerial):
    """模拟 Pico 因脏矩形超过画布容量而自动重启。"""

    def readline(self):
        """返回需要立即重连的画布容量致命错误。"""
        return build_frame(
            "EVENT",
            "FATAL:ValueError:脏矩形超过画布容量".encode("utf-8"),
        )


class HandshakeSerial(FakeSerial):
    """按顺序返回预置的 Pico 握手响应。"""

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)

    def readline(self):
        if self.responses:
            return self.responses.pop(0)
        return b""


class StyleUploadSerial(FakeSerial):
    """模拟逐块确认样式上传命令的 Pico 串口设备。"""

    def __init__(self):
        """初始化已解析命令和待返回响应。"""
        super().__init__()
        self.messages = []
        self.responses = []
        self.pending = bytearray()

    def write(self, data):
        """累计串口写入块，并在完整帧到达后生成命令响应。"""
        super().write(data)
        self.pending.extend(data)
        if not self.pending.endswith(b"\n"):
            return len(data)
        message_type, payload = parse_frame(self.pending)
        self.pending = bytearray()
        self.assert_message_type = message_type
        message = json.loads(zlib.decompress(base64.b64decode(payload)))
        self.messages.append(message)
        self.responses.append(build_frame("COMMAND", json.dumps({
            "status": "ok",
            "command": "uploadStyle",
            "request_id": message["request_id"],
            "data": message["params"],
        }).encode("utf-8")))
        return len(data)

    def readline(self):
        """返回下一个上传动作确认响应。"""
        return self.responses.pop(0) if self.responses else b""


class PicoClientTest(unittest.TestCase):
    """验证 Pico 客户端生成兼容固件的 JSON 数据包。"""

    def test_send_json_packet(self):
        """确认数据包使用 JSONZ 前缀并以换行结束。"""
        client = PicoJsonClient()
        client.serial = FakeSerial()

        client.send({"version": 1})

        self.assertTrue(client.serial.written.startswith(b"PV1:JSONZ:"))
        self.assertTrue(client.serial.written.endswith(b"\n"))

    def test_concurrent_serial_close_is_converted_to_disconnect_error(self):
        """确认 Windows 读取期间串口被关闭时不会泄漏 ctypes TypeError。"""
        client = PicoJsonClient()
        device = mock.Mock()
        device.is_open = True

        def fail_after_close():
            """模拟 serialwin32 在读取期间被其他线程释放句柄。"""
            device.is_open = False
            client.serial = None
            raise TypeError("byref() argument must be a ctypes instance, not 'NoneType'")

        device.readline.side_effect = fail_after_close
        client.serial = device

        with self.assertRaisesRegex(serial.SerialException, "串口已关闭"):
            client._read_protocol_frame("JSONZ")

    def test_reboot_sends_command_and_waits_for_ack(self):
        client = PicoJsonClient()
        client.serial = RebootSerial()

        client.reboot()

        self.assertEqual(bytes(client.serial.written), REBOOT_COMMAND)

    def test_large_json_uses_larger_serial_chunks(self):
        """确认较大 JSON 不再拆分成大量六十四字节串口写入。"""
        client = PicoJsonClient()
        client.serial = FakeSerial()

        client.send({"payload": "x" * 2800})

        self.assertLessEqual(client.serial.write_calls, 6)

    def test_slow_serial_write_emits_warning(self):
        """确认串口发送耗时过高时输出慢发送告警，便于定位 USB 背压。"""
        client = PicoJsonClient()
        client.serial = FakeSerial()

        with mock.patch(
            "pico_client.time.monotonic",
            side_effect=[0.0, 0.01, 0.16, 0.17, 0.25],
        ):
            with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
                client._write_packet(b"123", "JSONZ#1", build_elapsed_ms=5.0)

        self.assertIn("[协议慢发送][TEST][JSONZ#1]", "\n".join(logs.output))

    def test_style_upload_uses_small_flash_file_chunks(self):
        """确认大样式拆成小帧传输且不在单个 JSON 中携带完整源码。"""
        client = PicoJsonClient()
        client.serial = StyleUploadSerial()
        content = b"x" * 1300

        result = client.upload_style("style_clock.py", "clock", content)

        actions = [message["params"]["action"] for message in client.serial.messages]
        self.assertEqual(actions, ["begin", "data", "data", "data", "finish"])
        chunks = [
            base64.b64decode(message["params"]["content"])
            for message in client.serial.messages
            if message["params"]["action"] == "data"
        ]
        self.assertEqual(b"".join(chunks), content)
        self.assertTrue(all(len(chunk) <= 512 for chunk in chunks))
        self.assertEqual(result["action"], "finish")

    def test_style_delete_sends_command_and_waits_for_restart_ack(self):
        """确认删除样式使用 style.delete 命令并取得重启响应。"""
        client = PicoJsonClient()
        client.serial = StyleUploadSerial()

        result = client.delete_style("style_clock.py", "clock")

        message = client.serial.messages[0]
        self.assertEqual(message["command"], "style.delete")
        self.assertEqual(message["params"], {
            "filename": "style_clock.py",
            "style_name": "clock",
        })
        self.assertEqual(result["style_name"], "clock")

    def test_protocol_timing_extends_json_ack_wait(self):
        """确认 JSONZ 快照发送不再同步等待 Pico 返回 ACK。"""
        client = PicoJsonClient()
        client.serial = ProtocolTimingBeforeAckSerial()

        client.send({"version": 1})

        self.assertEqual(len(client.serial.responses), 2)

    @mock.patch("pico_client.time.monotonic")
    def test_json_ack_log_includes_send_elapsed(self, monotonic):
        """确认异步 JSON ACK 日志包含发送到 ACK 的耗时统计。"""
        monotonic.side_effect = iter([
            0.000, 0.005,
            0.010, 0.015, 0.020, 0.025, 0.030, 0.040,
            0.080,
        ])
        client = PicoJsonClient()
        client.serial = QueuedResponseSerial([])

        with self.assertLogs("pico-monitor.serial", level="DEBUG") as logs:
            client.send({"version": 1})
            client.serial.responses.append(build_frame("ACK", b"JSON:1"))
            client._drain_json_responses()

        text = "\n".join(logs.output)
        self.assertIn("[Pico -> Monitor][TEST][JSONZ 异步响应 响应]", text)
        self.assertIn("request_id=1", text)
        self.assertIn("发送到收到ACK耗时=70.0 ms", text)

    def test_bad_json_keeps_serial_connected(self):
        """确认缓存中的单帧 JSON 解析失败只记录警告并保持连接。"""
        client = PicoJsonClient()
        client.serial = QueuedResponseSerial([build_frame("ERR", b"BAD_JSON")])

        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            client._drain_json_responses()

        self.assertTrue(client.is_connected)
        self.assertTrue(any("BAD_JSON" in message for message in logs.output))

    def test_detailed_bad_json_keeps_serial_connected(self):
        """确认缓存中的详细 BAD_JSON 不会触发串口重连。"""
        client = PicoJsonClient()
        client.serial = QueuedResponseSerial([
            build_frame("ERR", b"BAD_JSON:MEMORY_ZLIB:MemoryError:memory allocation failed")
        ])

        with self.assertLogs("pico-monitor.serial", level="WARNING") as logs:
            client._drain_json_responses()

        self.assertTrue(client.is_connected)
        self.assertTrue(any("MEMORY_ZLIB" in message for message in logs.output))

    def test_memory_error_event_triggers_immediate_reconnect(self):
        """确认缓存中的 Pico 内存致命错误会立即转为重启异常。"""
        client = PicoJsonClient()
        client.serial = QueuedResponseSerial([
            build_frame("EVENT", b"FATAL:MemoryError:memory allocation failed, allocating 25601 bytes")
        ])

        with self.assertRaisesRegex(RuntimeError, "自动重启"):
            client._drain_json_responses()

    def test_canvas_capacity_error_triggers_immediate_reconnect(self):
        """确认缓存中的 Pico 画布容量致命错误会立即转为重启异常。"""
        client = PicoJsonClient()
        client.serial = QueuedResponseSerial([
            build_frame("EVENT", "FATAL:ValueError:脏矩形超过画布容量".encode("utf-8"))
        ])

        with self.assertRaisesRegex(RuntimeError, "自动重启"):
            client._drain_json_responses()

    def test_build_packet_for_development_mode(self):
        """确认开发模式打印内容与真实串口 JSON 协议行一致。"""
        packet = PicoJsonClient.build_packet({"host": "开发机"})

        self.assertTrue(packet.startswith(b"PV1:JSONZ:"))
        self.assertTrue(packet.endswith(b"\n"))
        message_type, payload = parse_frame(packet)
        self.assertEqual(message_type, "JSONZ")
        compressed = base64.b64decode(payload)
        self.assertEqual(compressed[0] >> 4, 1)
        self.assertIn(b'"host"', zlib.decompress(compressed))

    def test_development_json_matches_wire_payload(self):
        """确认开发日志展示压缩前实际发送的紧凑 JSON。"""
        snapshot = {
            "host": "开发机",
            "disks": [{"name": "logical"}],
            "physical_disks": [{"name": "physical"}],
        }

        payload = PicoJsonClient.build_json_payload(snapshot)
        _, compressed_payload = parse_frame(PicoJsonClient.build_packet(snapshot))

        envelope = json.loads(zlib.decompress(base64.b64decode(compressed_payload)))
        self.assertEqual(json.loads(payload), envelope["data"])
        self.assertEqual(envelope["mode"], "snapshot")
        self.assertNotIn(b'"disks"', payload)

    def test_wire_packet_omits_duplicate_logical_disks(self):
        """已有物理磁盘列表时不重复发送逻辑磁盘列表。"""
        snapshot = {
            "disks": [{"name": "logical"}],
            "physical_disks": [{"name": "physical"}],
        }

        _, payload = parse_frame(PicoJsonClient.build_packet(snapshot))
        decoded = json.loads(zlib.decompress(base64.b64decode(payload)))["data"]
        self.assertNotIn("disks", decoded)
        self.assertEqual(decoded["physical_disks"], snapshot["physical_disks"])
        self.assertIn("disks", snapshot)

    def test_ping_uses_pv1_frame(self):
        """握手使用带长度与 CRC 的 PV1 帧。"""
        self.assertTrue(PING_COMMAND.startswith(b"PV1:PING:"))
        self.assertTrue(PING_COMMAND.endswith(b"\n"))
        self.assertEqual(parse_frame(PING_COMMAND), ("PING", b""))

    def test_handshake_sends_only_pv1_ping(self):
        """独立 CDC 握手只发送一条 PV1 PING。"""
        device = HandshakeSerial([
            build_frame("PONG", json.dumps({
                "board_model": "rp2040_typec",
                "screen_color_profile": "st7789_2_4inch",
                "firmware_version": "1.2.3",
            }).encode()),
        ])

        self.assertTrue(PicoJsonClient()._handshake(device))
        self.assertEqual(device.write_calls, 1)
        self.assertEqual(device.written, PING_COMMAND)

    @mock.patch("pico_client.time.sleep")
    @mock.patch("pico_client.time.monotonic")
    def test_handshake_uses_configured_ping_interval(self, monotonic, sleep):
        """确认连续握手 PING 按配置的间隔发送。"""
        clock = iter(index * 0.4 for index in range(100))
        monotonic.side_effect = lambda: next(clock)
        device = HandshakeSerial([])

        self.assertFalse(PicoJsonClient(probe_interval=3.0)._handshake(device))

        self.assertEqual(sleep.call_args_list, [mock.call(3.0), mock.call(3.0)])
        self.assertEqual(device.write_calls, 3)

    def test_parse_pico_hardware_and_firmware_information(self):
        """确认 Monitor 能从新版握手读取板型、屏幕方案和固件版本。"""
        client = PicoJsonClient()
        client._parse_pong_payload(json.dumps({
            "board_model": "rp2040_typec",
            "screen_color_profile": "st7789_2_4inch",
            "firmware_version": "1.2.3",
            "width": 320,
            "height": 240,
        }).encode())
        self.assertEqual(client.device_information(), {
            "board_model": "rp2040_typec",
            "screen_color_profile": "st7789_2_4inch",
            "firmware_version": "1.2.3",
            "screen_width": 320,
            "screen_height": 240,
        })

    @mock.patch("pico_client.time.monotonic")
    def test_handshake_rejects_boot_messages_without_pong(self, monotonic):
        """BOOT 和屏幕 ACK 不能被误判为设备握手成功。"""
        clock = iter(index * 0.4 for index in range(100))
        monotonic.side_effect = lambda: next(clock)
        device = HandshakeSerial([
            b"BOOT:PICO_LCD_READY\n",
            b"ACK:LCD_FRAME:-1:TOTAL=276MS\n",
        ])

        self.assertFalse(PicoJsonClient()._handshake(device))

    def test_handshake_accepts_only_pong_and_parses_information(self):
        """收到真实 PONG 后才完成握手并记录硬件信息。"""
        device = HandshakeSerial([
            build_frame("PONG", json.dumps({
                "board_model": "rp2040_typec",
                "screen_color_profile": "st7789_2_4inch",
                "firmware_version": "1.2.3",
            }).encode()),
        ])
        client = PicoJsonClient()

        self.assertTrue(client._handshake(device))
        self.assertEqual(client.board_model, "rp2040_typec")

    def test_pico_info_argument(self):
        """确认命令行可以选择仅查询 Pico 设备信息。"""
        arguments = create_argument_parser().parse_args(["--pico-info"])
        self.assertTrue(arguments.pico_info)

    def test_pico_info_rejects_upgrade_action(self):
        """确认设备信息查询不会与固件升级同时执行。"""
        arguments = create_argument_parser().parse_args([
            "--pico-info", "--upgrade-pico",
        ])
        with self.assertRaisesRegex(SystemExit, "不能同时使用"):
            validate_arguments(arguments)

    def test_format_pico_information(self):
        """确认 Pico 信息使用清晰的中文字段输出。"""
        text = format_pico_information({
            "board_model": "rp2040_typec",
            "screen_color_profile": "st7789_2_4inch",
            "firmware_version": "1.2.3",
            "screen_width": 320,
            "screen_height": 240,
        })
        self.assertIn("Pico 开发板型号：rp2040_typec", text)
        self.assertIn("Pico 屏幕色彩方案：st7789_2_4inch", text)
        self.assertIn("Pico 固件版本：1.2.3", text)
        self.assertIn("Pico 屏幕分辨率：320 x 240", text)

    @mock.patch("pico_monitor._write_version_to_console")
    @mock.patch("pico_monitor.PicoJsonClient")
    def test_show_pico_information_connects_prints_and_closes(
        self, client_class, output
    ):
        """确认信息命令连接设备、输出结果并始终关闭串口。"""
        client = client_class.return_value
        client.device_information.return_value = {
            "board_model": "rp2040_usb",
            "screen_color_profile": "st7789vw_2inch",
            "firmware_version": "2.0.0",
        }
        self.assertEqual(show_pico_information("COM3"), 0)
        client_class.assert_called_once_with("COM3")
        client.connect.assert_called_once_with()
        client.close.assert_called_once_with()
        self.assertIn("rp2040_usb", output.call_args.args[0])

    def test_screen_rotation_argument(self):
        """确认屏幕旋转参数只接受固件支持的方向。"""
        arguments = create_argument_parser().parse_args(["--screen-rotation", "180"])
        self.assertEqual(arguments.screen_rotation, 180)

    def test_lcd_brightness_argument(self):
        """确认 LCD 背光亮度参数接受一至一百的百分比。"""
        arguments = create_argument_parser().parse_args(["--lcd-brightness", "35"])
        self.assertEqual(arguments.lcd_brightness, 35)

    def test_development_mode_argument(self):
        """确认命令行可以显式开启开发模式。"""
        arguments = create_argument_parser().parse_args(["--dev"])
        self.assertTrue(arguments.dev)

    @mock.patch("pico_monitor.MonitorService")
    @mock.patch("pico_monitor.configure_logging")
    @mock.patch("pico_monitor.validate_arguments")
    @mock.patch("pico_monitor.parse_monitor_arguments")
    def test_development_mode_forces_debug_logging(
        self, parse_arguments, validate, configure, service_class
    ):
        """确认开发模式启动时会输出 DEBUG 及以上级别日志。"""
        arguments = SimpleNamespace(
            dev=True,
            log_level="WARNING",
            worker=False,
            pico_info=False,
            upgrade_pico=False,
            update=False,
        )
        parse_arguments.return_value = arguments
        service = service_class.return_value
        service.run.return_value = 0

        self.assertEqual(main(), 0)

        validate.assert_called_once_with(arguments)
        configure.assert_called_once_with("DEBUG")
        service.close.assert_called_once_with()

    def test_debug_logging_prints_all_standard_levels(self):
        """确认 DEBUG 日志配置会输出 DEBUG 及以上全部标准级别日志。"""
        stream = io.StringIO()
        with mock.patch("monitor_core.console._configure_standard_streams", return_value=stream):
            configure_logging("DEBUG")
            logger = logging.getLogger("pico-monitor.dev-log-test")
            logger.debug("调试日志")
            logger.info("普通日志")
            logger.warning("告警日志")
            _stop_log_listener()

        content = stream.getvalue()
        self.assertIn("[DEBUG] 调试日志", content)
        self.assertIn("[INFO] 普通日志", content)
        self.assertIn("[WARNING] 告警日志", content)

    def test_version_argument_prints_build_version(self):
        """确认命令行版本参数输出统一构建版本并成功退出。"""
        with mock.patch("pico_monitor.MONITOR_VERSION", "1.2.3"):
            with mock.patch("sys.stdout") as output:
                with self.assertRaises(SystemExit) as exit_context:
                    create_argument_parser().parse_args(["--version"])

        self.assertEqual(exit_context.exception.code, 0)
        output.write.assert_called_once_with("pico-monitor 1.2.3\n")
        output.flush.assert_called_once_with()

    def test_startup_log_contains_build_version(self):
        """确认服务启动日志包含当前 Monitor 构建版本。"""
        with mock.patch("pico_monitor.MONITOR_VERSION", "1.2.3"):
            with self.assertLogs("pico-monitor", level="INFO") as logs:
                log_monitor_version()

        self.assertIn("Pico Monitor 启动：版本=1.2.3", logs.output[0])

    def test_stop_does_not_close_serial_from_control_thread(self):
        """确认停止请求仅唤醒主循环，避免控制线程与串口读取并发关闭。"""
        service = MonitorService.__new__(MonitorService)
        service.stopping = mock.Mock()
        service.client = mock.Mock()

        service.stop()

        service.stopping.set.assert_called_once_with()
        service.client.close.assert_not_called()

    def test_sending_uses_latest_snapshot_without_waiting_for_next_collection(self):
        """确认后台采集尚未发布新结果时，发送链路立即复用最近成功快照。"""
        service = MonitorService.__new__(MonitorService)
        service._latest_collected_snapshot = {"version": 1, "sequence": 7}
        service._latest_collection_error = None
        service.stopping = mock.Mock()
        service.stopping.is_set.return_value = False
        service._collect_snapshot = mock.Mock(side_effect=AssertionError("发送线程不应同步采集"))

        snapshot = service._snapshot_for_sending()

        self.assertEqual(snapshot["sequence"], 7)
        service._collect_snapshot.assert_not_called()

    def test_initial_snapshot_is_complete_and_marks_metrics_unavailable(self):
        """确认首次采集完成前也能立即发送结构完整的默认数据。"""
        arguments = SimpleNamespace(
            interval=0.5,
            screen_rotation=0,
            lcd_brightness=57,
            network_unit="MB",
            lcd_style="horizontal_disk4x",
        )

        snapshot = MonitorService._create_initial_snapshot(arguments)

        self.assertIsNone(snapshot["cpu"]["percent"])
        self.assertIsNone(snapshot["memory"]["percent"])
        self.assertFalse(snapshot["network"]["online"])
        self.assertEqual(len(snapshot["cpu"]["history"]), 24)
        self.assertEqual(snapshot["display"]["collection_interval_ms"], 500)

    def test_dev_mode_can_be_hot_updated_without_restarting_service(self):
        """确认工作进程可以直接应用托盘下发的开发模式开关。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(dev=False, log_level="WARNING")

        with mock.patch("monitor_core.style_commands.configure_logging") as configure:
            service.apply_dev_config({"enabled": True})

        self.assertTrue(service.arguments.dev)
        configure.assert_called_once_with("DEBUG")

    def test_development_mode_stops_reconnecting_without_pico(self):
        """确认开发模式首次连接失败后直接进入 JSON 输出循环。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            port=None,
            ping_target="127.0.0.1",
            interval=1.0,
            reconnect_interval=3.0,
            screen_rotation=0,
            network_unit="MB",
            lcd_style="horizontal_disk",
            dev=True,
        )
        service.stopping = mock.Mock()
        service.stopping.is_set.return_value = False
        service.client = mock.Mock()
        service.client.is_connected = False
        service.client.available_ports.return_value = frozenset()
        service.client.connect.side_effect = RuntimeError("未找到 Pico")
        service._run_development_loop = mock.Mock(return_value=0)
        service._collection_thread = mock.Mock()
        service._collection_thread.is_alive.return_value = True

        result = service.run()

        self.assertEqual(result, 0)
        service.client.connect.assert_called_once_with()
        service._run_development_loop.assert_called_once_with()

    def test_connection_failure_retries_when_port_already_exists(self):
        """确认首次探测过早时，不要求 COM 口再次增加也会延迟重试。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            port=None,
            ping_target="127.0.0.1",
            interval=1.0,
            reconnect_interval=3.0,
            screen_rotation=0,
            network_unit="MB",
            lcd_style="horizontal_disk",
            dev=False,
            upgrade_pico=False,
            once=False,
        )
        service.stopping = mock.Mock()
        service.stopping.is_set.side_effect = [False, False, False, True]
        service.client = mock.Mock()
        service.client.is_connected = False
        service.client.available_ports.return_value = frozenset({"COM1"})
        service.client.connect.side_effect = RuntimeError("未找到 Pico")
        service._collection_thread = mock.Mock()
        service._collection_thread.is_alive.return_value = True

        self.assertEqual(service.run(), 0)

        self.assertEqual(service.client.connect.call_count, 3)
        service.stopping.wait.assert_any_call(3.0)

    def test_connected_send_failure_retries_without_usb_addition(self):
        """确认已连接后的通信异常不再等待新增 COM 口才重连。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            port=None,
            ping_target="127.0.0.1",
            interval=1.0,
            reconnect_interval=3.0,
            screen_rotation=0,
            network_unit="MB",
            lcd_style="horizontal_disk",
            dev=False,
            upgrade_pico=False,
            once=False,
        )
        service.stopping = mock.Mock()
        service.stopping.is_set.side_effect = [False, False, True]
        service.stopping.wait.return_value = False
        service.client = mock.Mock()
        service.client.is_connected = True
        service.client.available_ports.return_value = frozenset({"COM11"})
        service.client.send.side_effect = RuntimeError("等待 Pico JSON 接收确认超时")
        service._collect_snapshot = mock.Mock(return_value={"version": 1})
        service._wait_for_usb_addition = mock.Mock(return_value=False)
        service.custom_style_catalog_requested = mock.Mock()
        service.custom_style_catalog_requested.is_set.return_value = False
        service.screenshot_requested = mock.Mock()
        service.screenshot_requested.is_set.return_value = False
        service.custom_style_uploads = mock.Mock()
        service.custom_style_uploads.empty.return_value = True
        service.custom_style_deletes = mock.Mock()
        service.custom_style_deletes.empty.return_value = True
        service.reboot_requested = mock.Mock()
        service.reboot_requested.is_set.return_value = False
        service._collection_thread = mock.Mock()
        service._collection_thread.is_alive.return_value = True
        service._latest_collected_snapshot = {"version": 1}

        self.assertEqual(service.run(), 0)

        service._wait_for_usb_addition.assert_not_called()
        service.stopping.wait.assert_any_call(3.0)

    def test_transmit_worker_drops_snapshot_when_previous_send_is_busy(self):
        """确认上一帧仍在串口发送时，新快照会被直接丢弃而不排队。"""
        service = MonitorService.__new__(MonitorService)
        service.stopping = threading.Event()
        service.client = mock.Mock()
        send_started = threading.Event()
        release_send = threading.Event()

        def slow_send(snapshot):
            """模拟串口写入被驱动背压阻塞。"""
            send_started.set()
            release_send.wait(1.0)

        service.client.send.side_effect = slow_send
        service._start_transmit_worker()
        self.assertTrue(service._submit_snapshot_for_transmission({"sequence": 1}))
        self.assertTrue(send_started.wait(1.0))

        with self.assertLogs("pico-monitor", level="DEBUG") as logs:
            accepted = service._submit_snapshot_for_transmission({"sequence": 2})

        release_send.set()
        service._wait_for_transmit_idle()
        service._stop_transmit_worker(wait=True)

        self.assertFalse(accepted)
        service.client.send.assert_called_once_with({"sequence": 1})
        self.assertIn("JSON 快照发送仍在进行，丢弃本轮快照", "\n".join(logs.output))

    def test_transmit_worker_error_is_raised_on_main_loop(self):
        """确认发送线程中的通信异常会转交主循环继续走重连流程。"""
        service = MonitorService.__new__(MonitorService)
        service.stopping = threading.Event()
        service.client = mock.Mock()
        service.client.send.side_effect = RuntimeError("串口写入失败")

        service._start_transmit_worker()
        service._submit_snapshot_for_transmission({"version": 1})

        with self.assertRaisesRegex(RuntimeError, "串口写入失败"):
            service._wait_for_interval_or_transmit_error(1.0)

        service._stop_transmit_worker(wait=True)

    def test_usb_removal_does_not_trigger_probe(self):
        """拔出串口只更新基线，直到后续插入新端口才返回。"""
        service = MonitorService.__new__(MonitorService)
        service.stopping = mock.Mock()
        service.stopping.is_set.side_effect = [False, False, False]
        service.client = mock.Mock()
        service.client.available_ports.side_effect = [
            frozenset({"COM1"}),
            frozenset({"COM1"}),
            frozenset({"COM1", "COM4"}),
        ]

        self.assertTrue(service._wait_for_usb_addition({"COM1", "COM4"}))
        self.assertEqual(service.stopping.wait.call_count, 2)

    def test_ping_and_network_unit_arguments(self):
        """确认 Ping 默认地址和网络速率单位可以独立配置。"""
        defaults = create_argument_parser().parse_args([])
        self.assertEqual(defaults.ping_target, "www.baidu.com")
        self.assertEqual(defaults.serial_probe_interval, 3.0)
        arguments = create_argument_parser().parse_args(["--ping-target", "1.1.1.1", "--network-unit", "Mbps"])
        self.assertEqual(arguments.ping_target, "1.1.1.1")
        self.assertEqual(arguments.network_unit, "Mbps")

    def test_yaml_config_supplies_nested_defaults(self):
        """确认 Linux YAML 配置能作为命令行参数默认值。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
            config_file.write(
                "\n".join((
                    "serial:",
                    "  port: /dev/ttyACM1",
                    "network:",
                    "  ping_target: 1.1.1.1",
                    "  unit: Mbps",
                    "monitor:",
                    "  interval: 2.5",
                    "  dev: false",
                    "screen:",
                    "  lcd_brightness: 80",
                    "collection_tasks:",
                    "  intervals:",
                    "    cpu_memory: 2",
                    "qbittorrent:",
                    "  enabled: true",
                    "  address: http://127.0.0.1:8080",
                    "  username: admin",
                    "  password: password",
                ))
            )
            config_path = config_file.name
        try:
            arguments = parse_monitor_arguments(["--config", config_path])
        finally:
            os.unlink(config_path)

        self.assertEqual(arguments.port, "/dev/ttyACM1")
        self.assertEqual(arguments.ping_target, "1.1.1.1")
        self.assertEqual(arguments.network_unit, "Mbps")
        self.assertEqual(arguments.interval, 2.5)
        self.assertEqual(arguments.lcd_brightness, 80)
        self.assertFalse(arguments.dev)
        self.assertEqual(arguments.collection_task_intervals["cpu_memory"], 2)
        self.assertTrue(arguments.qbittorrent_enabled)
        validate_arguments(arguments)

    def test_legacy_environment_config_is_still_supported(self):
        """确认旧版 EnvironmentFile 配置升级后仍可读取。"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as config_file:
            config_file.write(
                "\n".join((
                    'PICO_MONITOR_PING_TARGET="8.8.8.8"',
                    'PICO_MONITOR_NETWORK_UNIT="Mbps"',
                    'PICO_MONITOR_COLLECTION_TASK_INTERVALS="{\\"网络采集\\": 3}"',
                ))
            )
            config_path = config_file.name
        try:
            config = load_monitor_config(config_path)
            arguments = create_argument_parser(config).parse_args([])
        finally:
            os.unlink(config_path)

        self.assertEqual(arguments.ping_target, "8.8.8.8")
        self.assertEqual(arguments.network_unit, "Mbps")
        self.assertEqual(arguments.collection_task_intervals["network"], 3)

    def test_lcd_style_argument(self):
        """确认 monitor 可以选择固件提供的内置 LCD 样式。"""
        for style_name in ("default", "disk", "horizontal_disk"):
            arguments = create_argument_parser().parse_args(["--lcd-style", style_name])
            self.assertEqual(arguments.lcd_style, style_name)

    def test_qbittorrent_collection_is_disabled_by_default(self):
        """确认未显式开启时不会要求或连接 qBittorrent。"""
        arguments = create_argument_parser().parse_args([])
        self.assertFalse(arguments.qbittorrent_enabled)
        validate_arguments(arguments)

    def test_qbittorrent_enabled_requires_connection_parameters(self):
        """确认开启采集后地址、账号和密码均为必填项。"""
        arguments = create_argument_parser().parse_args(["--qbittorrent-enabled"])
        with self.assertRaises(SystemExit):
            validate_arguments(arguments)

    def test_qbittorrent_enabled_accepts_complete_configuration(self):
        """确认完整 qBittorrent 连接配置能够通过参数校验。"""
        arguments = create_argument_parser().parse_args([
            "--qbittorrent-enabled",
            "--qbittorrent-address", "http://127.0.0.1:8080",
            "--qbittorrent-username", "admin",
            "--qbittorrent-password", "password",
        ])
        validate_arguments(arguments)

    def test_disk_health_display_test_arguments(self):
        """验证可指定从一开始的磁盘序号和健康测试等级。"""
        arguments = create_argument_parser().parse_args([
            "--disk-health-test-index", "2",
            "--disk-health-test-level", "5",
        ])

        self.assertEqual(arguments.disk_health_test_index, 2)
        self.assertEqual(arguments.disk_health_test_level, 5)

    def test_disk_health_display_test_defaults_to_level_three(self):
        """验证启用磁盘健康显示测试时默认使用三级告警。"""
        arguments = create_argument_parser().parse_args([
            "--disk-health-test-index", "1",
        ])

        self.assertEqual(arguments.disk_health_test_level, 3)

    def test_apply_disk_health_display_test_to_selected_disk(self):
        """验证健康显示测试只覆盖用户指定的物理磁盘。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            disk_health_test_index=2,
            disk_health_test_level=4,
        )
        disks = [{"name": "DISK0", "health": 1}, {"name": "DISK1", "health": 1}]
        snapshot = {"physical_disks": [dict(item) for item in disks], "disks": disks}

        service._apply_disk_health_test(snapshot)

        self.assertEqual([item["health"] for item in snapshot["physical_disks"]], [1, 4])
        self.assertEqual([item["health"] for item in snapshot["disks"]], [1, 4])

    def test_disk_health_display_test_ignores_collection_not_ready(self):
        """验证后台磁盘采集尚未完成时不会误报测试序号越界。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            disk_health_test_index=2,
            disk_health_test_level=4,
        )

        with self.assertNoLogs("pico-monitor", level="WARNING"):
            service._apply_disk_health_test({"physical_disks": [], "disks": []})

    def test_disk_health_display_test_warns_real_out_of_range_once(self):
        """验证采集完成后的真实越界只记录一次警告，避免周期性刷屏。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            disk_health_test_index=2,
            disk_health_test_level=4,
        )
        snapshot = {"physical_disks": [{"name": "DISK0", "health": 1}]}

        with self.assertLogs("pico-monitor", level="WARNING") as messages:
            service._apply_disk_health_test(snapshot)
            service._apply_disk_health_test(snapshot)

        self.assertEqual(1, len(messages.output))


class SystemCollectorTest(unittest.TestCase):
    """验证系统采集器输出 Pico 仪表盘需要的字段。"""

    def test_network_rates_use_selected_interface_counter(self):
        """确认网络速率仅根据主通信接口的累计字节差值计算。"""
        collector = SystemInformationCollector("127.0.0.1")
        counters = [
            ("eth0", 1000, 2000),
            ("eth0", 1600, 2900),
        ]

        with mock.patch.object(collector, "_network_counter", side_effect=counters):
            with mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 11.0)):
                self.assertEqual(collector._network_rates("192.168.1.2")[:2], (0, 0))
                self.assertEqual(collector._network_rates("192.168.1.2")[:2], (600, 900))

    @mock.patch("system_monitor.platform.system", return_value="Linux")
    @mock.patch("system_monitor.psutil.cpu_freq")
    def test_cpu_frequency_averages_current_core_speeds(self, cpu_freq, system):
        """确认 CPU GHz 根据各逻辑处理器的实时 MHz 平均值计算。"""
        del system
        cpu_freq.return_value = [SimpleNamespace(current=4200), SimpleNamespace(current=4400)]

        self.assertEqual(SystemInformationCollector._cpu_frequency_ghz(), 4.3)

    @mock.patch("system_monitor.platform.system", return_value="Windows")
    @mock.patch.object(SystemInformationCollector, "_windows_cpu_current_frequency_mhz", return_value=4287.6)
    def test_windows_cpu_frequency_uses_native_current_speed(self, current_frequency, system):
        """确认 Windows 使用原生接口的实时频率而不是 CPU 基准速度。"""
        del current_frequency, system

        self.assertEqual(SystemInformationCollector._cpu_frequency_ghz(), 4.29)

    def test_network_rates_reset_baseline_after_interface_change(self):
        """确认出口接口切换后重置基线，避免累计计数差产生速率尖峰。"""
        collector = SystemInformationCollector("127.0.0.1")
        counters = [
            ("eth0", 1000, 2000),
            ("bond0", 500000, 800000),
        ]

        with mock.patch.object(collector, "_network_counter", side_effect=counters):
            with mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 11.0)):
                collector._network_rates("192.168.1.2")
                rates = collector._network_rates("192.168.1.2")

        self.assertEqual(rates[:2], (0, 0))
        self.assertEqual(rates[2:], (500000, 800000))

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures", return_value={})
    @mock.patch.object(SystemInformationCollector, "_cpu_temperature", return_value=None)
    def test_collect_snapshot_structure(self, temperature, disk_temperatures):
        """确认完整快照包含四组核心硬件指标。"""
        del temperature, disk_temperatures
        collector = SystemInformationCollector("127.0.0.1")
        collector.gpu_monitor.snapshot = mock.Mock(return_value=({
            "percent": 61.5,
            "dedicated_memory_used_bytes": 2_000_000_000,
            "dedicated_memory_total_bytes": 8_000_000_000,
            "temperature_c": 67.0,
        }, 1))
        snapshot = collector.collect()
        self.assertEqual(snapshot["version"], 1)
        self.assertTrue({"cpu", "memory", "disk", "disks", "physical_disks", "fps", "power", "network"}.issubset(snapshot))
        self.assertTrue({"value", "history", "source", "process_id", "process_name"}.issubset(snapshot["fps"]))
        self.assertEqual(len(snapshot["fps"]["history"]), 24)
        self.assertTrue({"watts", "source", "scope", "history"}.issubset(snapshot["power"]))
        self.assertTrue({"receive_bytes", "transmit_bytes"}.issubset(snapshot["network"]))
        self.assertIn("frequency_ghz", snapshot["cpu"])
        self.assertTrue({
            "percent", "dedicated_memory_used_bytes", "dedicated_memory_total_bytes", "temperature_c", "history"
        }.issubset(snapshot["gpu"]))
        self.assertNotIn("history", snapshot["disk"])

    def test_physical_disk_statistics_contains_temperature(self):
        """验证发送给 Pico 的物理磁盘统计包含温度和容量指标。"""
        statistics = SystemInformationCollector._physical_disk_statistics([
            {
                "name": "NVME0",
                "devices": ["C:"],
                "mountpoints": ["C:\\"],
                "used_bytes": 400,
                "total_bytes": 1000,
                "percent": 40,
                "temperature_c": 42.5,
            }
        ])

        self.assertEqual(statistics[0]["name"], "NVME0")
        self.assertEqual(statistics[0]["temperature_c"], 42.5)
        self.assertEqual(statistics[0]["health"], 0)
        self.assertEqual(statistics[0]["total_bytes"], 1000)
        self.assertEqual(statistics[0]["read_bps"], 0)
        self.assertEqual(statistics[0]["write_history"], [])

    def test_smart_health_classification_uses_overall_status_and_attributes(self):
        """验证 SMART 总体失败和坏块指标会映射到约定的健康等级。"""
        self.assertEqual(
            SystemInformationCollector._classify_smart_health({"smart_status": {"passed": False}}),
            5,
        )
        warning_payload = {
            "smart_status": {"passed": True},
            "ata_smart_attributes": {"table": [
                {"name": "Current_Pending_Sector", "raw": {"value": 2}, "when_failed": "-"}
            ]},
        }
        self.assertEqual(SystemInformationCollector._classify_smart_health(warning_payload), 3)
        notice_payload = {
            "smart_status": {"passed": True},
            "ata_smart_attributes": {"table": [
                {"name": "Reallocated_Sector_Ct", "raw": {"value": 1}, "when_failed": "-"}
            ]},
        }
        self.assertEqual(SystemInformationCollector._classify_smart_health(notice_payload), 2)

    @mock.patch.object(SystemInformationCollector, "_read_smart_health", return_value=1)
    @mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 100.0, 1900.0))
    def test_disk_health_checks_at_startup_and_every_thirty_minutes(self, monotonic, read_health):
        """验证 SMART 健康检查启动时执行，并在三十分钟内复用缓存。"""
        del monotonic
        collector = SystemInformationCollector.__new__(SystemInformationCollector)
        collector.disk_health_cache = {}
        collector.disk_health_time = 0.0
        descriptors = [("sda", "/dev/sda", "sat")]

        self.assertEqual(collector._disk_health(descriptors), {"sda": 1})
        self.assertEqual(collector._disk_health(descriptors), {"sda": 1})
        self.assertEqual(collector._disk_health(descriptors), {"sda": 1})

        self.assertEqual(read_health.call_count, 2)

    @mock.patch.object(SystemInformationCollector, "_disk_hardware_signature")
    def test_disk_hardware_change_invalidates_smart_caches(self, hardware_signature):
        """验证磁盘热插拔后会立即清空 SMART 健康度和温度缓存。"""
        hardware_signature.side_effect = (((), ("sda",)), ((), ("sda", "sdb")))
        collector = SystemInformationCollector.__new__(SystemInformationCollector)
        collector.disk_hardware_signature = None
        collector.disk_temperature_cache = {"sda": 40.0}
        collector.disk_temperature_time = 10.0
        collector.disk_health_cache = {"sda": 1}
        collector.disk_health_time = 10.0

        self.assertFalse(collector._refresh_disk_hardware_state())
        self.assertTrue(collector._refresh_disk_hardware_state())

        self.assertEqual(collector.disk_temperature_cache, {})
        self.assertEqual(collector.disk_temperature_time, 0.0)
        self.assertEqual(collector.disk_health_cache, {})
        self.assertEqual(collector.disk_health_time, 0.0)

    @mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 12.0))
    @mock.patch("system_monitor.psutil.disk_io_counters")
    @mock.patch.object(SystemInformationCollector, "_windows_device_number", return_value=0)
    def test_disk_rates_include_realtime_and_history(self, device_number, disk_io_counters, monotonic):
        """验证每块物理磁盘会计算实时读写速度并维护固定长度历史数据。"""
        del device_number, monotonic
        disk_io_counters.side_effect = (
            {"PhysicalDrive0": SimpleNamespace(read_bytes=1000, write_bytes=2000)},
            {"PhysicalDrive0": SimpleNamespace(read_bytes=5000, write_bytes=8000)},
        )
        collector = SystemInformationCollector.__new__(SystemInformationCollector)
        collector.last_disk_io = None
        collector.last_disk_io_time = None
        collector.disk_io_histories = {}
        disks = [{"name": "DISK0 NVME", "devices": ["C:"]}]

        first = collector._disk_rates(disks)
        self.assertEqual((first[0]["read_bps"], first[0]["write_bps"]), (0, 0))
        second = collector._disk_rates(disks)

        self.assertEqual((second[0]["read_bps"], second[0]["write_bps"]), (2000, 3000))
        self.assertEqual(second[0]["read_history"][-2:], [0, 2000])
        self.assertEqual(second[0]["write_history"][-2:], [0, 3000])
        self.assertEqual(len(second[0]["read_history"]), 24)

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures", return_value={})
    @mock.patch.object(SystemInformationCollector, "_windows_device_number", side_effect=(0, 0))
    @mock.patch("system_monitor.platform.system", return_value="Windows")
    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_windows_disk_details_use_device_number_without_storage_permission(
        self, disk_partitions, disk_usage, system, device_number, disk_temperatures
    ):
        """验证 Windows 存储命令无权限时仍能按物理磁盘编号合并多个分区。"""
        del system, device_number, disk_temperatures
        disk_partitions.return_value = [
            SimpleNamespace(device="C:\\", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            SimpleNamespace(device="D:\\", mountpoint="D:\\", fstype="NTFS", opts="rw,fixed"),
        ]
        disk_usage.side_effect = (
            SimpleNamespace(total=1000, used=400),
            SimpleNamespace(total=2000, used=500),
        )
        collector = SystemInformationCollector.__new__(SystemInformationCollector)

        disks = collector._disk_details()

        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["name"], "DISK0")
        self.assertEqual(disks[0]["devices"], ["C:\\", "D:\\"])

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures")
    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_details_include_capacity_usage_and_temperature(self, disk_partitions, disk_usage, disk_temperatures):
        """确认每个磁盘明细包含容量、占用情况和对应温度。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", fstype="NTFS", opts="rw,fixed"),
        ]
        disk_usage.side_effect = (
            SimpleNamespace(total=1000, used=400, percent=40),
            SimpleNamespace(total=2000, used=500, percent=25),
        )
        disk_temperatures.return_value = {
            os.path.normcase("C:"): {"name": "NVME0", "temperature_c": 41.0},
            os.path.normcase("D:"): {"name": "SATA1", "temperature_c": 36.0},
        }
        collector = SystemInformationCollector.__new__(SystemInformationCollector)

        disks = collector._disk_details()

        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["name"], "NVME0")
        self.assertEqual(disks[0]["temperature_c"], 41.0)
        self.assertEqual((disks[1]["used_bytes"], disks[1]["total_bytes"], disks[1]["percent"]), (500, 2000, 25.0))

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures")
    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_details_merge_partitions_on_same_physical_disk(self, disk_partitions, disk_usage, disk_temperatures):
        """确认同一物理硬盘的多个分区会聚合为一个磁盘明细。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", fstype="NTFS", opts="rw,fixed"),
        ]
        disk_usage.side_effect = (
            SimpleNamespace(total=1000, used=400, percent=40),
            SimpleNamespace(total=2000, used=500, percent=25),
        )
        sensor = {"name": "DISK0 NVME", "temperature_c": 40.0}
        disk_temperatures.return_value = {os.path.normcase("C:"): sensor, os.path.normcase("D:"): sensor}
        collector = SystemInformationCollector.__new__(SystemInformationCollector)

        disks = collector._disk_details()

        self.assertEqual(len(disks), 1)
        self.assertEqual((disks[0]["used_bytes"], disks[0]["total_bytes"], disks[0]["percent"]), (900, 3000, 30.0))
        self.assertEqual(disks[0]["mountpoints"], ["C:\\", "D:\\"])

    @mock.patch.object(SystemInformationCollector, "_read_unassigned_disk_temperatures", return_value=[])
    @mock.patch.object(SystemInformationCollector, "_discover_linux_disks", return_value=[("sdb", "/dev/sdb", None)])
    @mock.patch.object(SystemInformationCollector, "_read_linux_disk_temperature", return_value=38.0)
    @mock.patch.object(SystemInformationCollector, "_linux_backing_disks")
    @mock.patch("system_monitor.platform.system", return_value="Linux")
    def test_linux_disk_temperatures_resolve_logical_devices(
        self, system, backing_disks, read_temperature, discover_disks, unassigned_temperatures
    ):
        """确认 Linux 逻辑卷映射到底层物理盘，并排除 loop 等虚拟设备。"""
        del system, discover_disks, unassigned_temperatures
        backing_disks.side_effect = lambda device: {
            "/dev/mapper/data": ("sdb",),
            "/dev/loop0": (),
        }[device]
        collector = SystemInformationCollector.__new__(SystemInformationCollector)
        collector.disk_temperature_cache = {}
        collector.disk_temperature_time = 0.0

        temperatures = collector._disk_temperatures(["/dev/mapper/data", "/dev/loop0"])

        mapper_key = os.path.normcase("/dev/mapper/data")
        loop_key = os.path.normcase("/dev/loop0")
        self.assertEqual(temperatures[mapper_key]["name"], "sdb")
        self.assertEqual(temperatures[mapper_key]["temperature_c"], 38.0)
        self.assertNotIn(loop_key, temperatures)
        read_temperature.assert_called_once_with("/dev/sdb", None, "sdb")

    @mock.patch("system_monitor.subprocess.run")
    def test_smart_scan_discovers_sata_nvme_and_raid_disks(self, process_runner):
        """确认 SMART 自动扫描能够发现 SATA、NVMe 和 RAID 控制器磁盘。"""
        process_runner.return_value = SimpleNamespace(stdout=json.dumps({
            "devices": [
                {"name": "/dev/sda", "type": "sat"},
                {"name": "/dev/nvme0", "type": "nvme"},
                {"name": "/dev/bus/0", "type": "megaraid,0"},
                {"name": "/dev/sdb", "type": "sat", "open_error": "拒绝访问"},
            ]
        }))

        devices = SystemInformationCollector._scan_linux_smart_devices()

        self.assertEqual(devices, {
            "sda": ("/dev/sda", "sat"),
            "nvme0n1": ("/dev/nvme0", "nvme"),
            "megaraid0": ("/dev/bus/0", "megaraid,0"),
        })

    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_usage_sums_all_local_disks(self, disk_partitions, disk_usage):
        """确认磁盘容量汇总全部本地分区并跳过重复挂载和光驱。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\mirror", opts="rw,fixed"),
            SimpleNamespace(device="E:", mountpoint="E:\\", opts="ro,cdrom"),
        ]
        usages = {
            "C:\\": SimpleNamespace(total=1000, used=400),
            "D:\\": SimpleNamespace(total=2000, used=500),
        }
        disk_usage.side_effect = lambda mountpoint: usages[mountpoint]

        used, total, percent = SystemInformationCollector._disk_usage()

        self.assertEqual((used, total), (900, 3000))
        self.assertEqual(percent, 30.0)
        self.assertEqual(disk_usage.call_count, 2)

    @mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 12.0))
    @mock.patch.object(PowerMonitor, "_read_energy_counters")
    def test_power_monitor_calculates_watts(self, energy_counters, monotonic):
        """确认相邻 RAPL 能耗读数能够换算为实时功耗瓦数。"""
        del monotonic
        energy_counters.side_effect = (
            {"package0": (1_000_000, 10_000_000)},
            {"package0": (5_000_000, 10_000_000)},
        )
        monitor = PowerMonitor()

        first = monitor.snapshot()
        second = monitor.snapshot()

        self.assertIsNone(first["watts"])
        self.assertEqual(second["watts"], 2.0)
        self.assertEqual(second["source"], "linux_rapl")

    def test_power_monitor_follows_linked_directories(self):
        """确认功耗目录扫描会进入 Debian sysfs 使用的目录符号链接。"""
        class FakePath:
            """模拟可解析到真实目录的 sysfs 路径节点。"""

            def __init__(self, name, resolved, children=(), directory=False):
                """保存节点名称、真实路径、子节点和目录标记。"""
                self.name = name
                self.resolved = resolved
                self.children = children
                self.directory = directory

            def resolve(self):
                """返回节点解析后的真实路径标识。"""
                return self.resolved

            def iterdir(self):
                """返回当前模拟目录的直接子节点。"""
                return iter(self.children)

            def is_dir(self):
                """返回当前节点是否可作为目录遍历。"""
                return self.directory

        energy = FakePath("energy_uj", "真实区域/energy_uj")
        linked_zone = FakePath("intel-rapl:0", "真实区域", (energy,), True)
        duplicate_link = FakePath("package-0", "真实区域", (energy,), True)
        root = FakePath("powercap", "powercap", (linked_zone, duplicate_link), True)

        paths = list(PowerMonitor._iter_energy_paths(root))

        self.assertEqual(paths, ["真实区域/energy_uj"])


if __name__ == "__main__":
    unittest.main()
