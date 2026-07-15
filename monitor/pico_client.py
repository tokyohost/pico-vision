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



"""发现 Pico LCD，并通过 USB 或 WebSocket 可靠发送 JSON 系统快照。"""


import json
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import serial
from serial.tools import list_ports

from json_ack_timing_cache import ExpiringJsonAckTimingCache
from net import WebSocketDevice
from pico_ack import PicoJsonAckMixin
from pico_commands import PicoCommandMixin
from pico_protocol import (
    JsonAckTimeoutError,
    PING_COMMAND,
    PicoRestartingError,
    build_command_packet,
    build_frame,
    build_jsonz_packet,
    crc16_ccitt,
    is_restarting_fatal,
    parse_frame,
)
from pico_snapshot import (
    build_json_payload,
    build_packet,
    build_snapshot_packets,
    snapshot_envelope_payload,
    split_snapshot_payloads,
    wire_snapshot,
)
from usbCdcFramework import UsbCdcFramework


JSON_ACK_TIMEOUT = 8.0
JSON_PROGRESS_GRACE_SECONDS = 2.0
SERIAL_SLOW_SEND_WARNING_MS = 200.0
SERIAL_WRITE_CHUNK_SIZE = 511
ESP32_S3_SERIAL_WRITE_CHUNK_SIZE = 511
ESP32_S3_SERIAL_WRITE_CHUNK_PAUSE_SECONDS = 0.002
LOGGER = logging.getLogger("pico-monitor.serial")


_is_restarting_fatal = is_restarting_fatal


class PicoJsonClient(PicoCommandMixin, PicoJsonAckMixin):
    """封装 Pico LCD 自动发现、握手、数据发送和连接清理。"""

    _wire_snapshot = staticmethod(wire_snapshot)
    build_json_payload = staticmethod(build_json_payload)
    _snapshot_envelope_payload = staticmethod(snapshot_envelope_payload)
    build_packet = staticmethod(build_packet)
    _split_snapshot_payloads = staticmethod(split_snapshot_payloads)
    build_snapshot_packets = staticmethod(build_snapshot_packets)
    _build_jsonz_packet = staticmethod(build_jsonz_packet)
    build_command_packet = staticmethod(build_command_packet)

    def __init__(self, configured_port=None, probe_interval=3.0, cancellation_event=None, websocket_url=None):
        """保存可选串口或 WebSocket 地址并初始化断开状态。"""
        self.configured_port = configured_port
        self.websocket_url = str(websocket_url).strip() if websocket_url else None
        self.probe_interval = max(0.0, float(probe_interval))
        self.cancellation_event = cancellation_event
        self.serial = None
        self.board_model = None
        self.lcd_device_type = None
        self.screen_color_profile = None
        self.firmware_version = None
        self.screen_width = None
        self.screen_height = None
        self.styles = []
        self.net_status = None
        self._json_request_sequence = 0
        self._json_ack_pending = ExpiringJsonAckTimingCache()
        self._json_ack_lock = threading.Lock()
        self._json_ack_events = {}
        self.transport = None

    @property
    def is_connected(self):
        """返回当前 USB CDC 或 WebSocket 连接是否已经打开。"""
        return self.serial is not None and self.serial.is_open

    @property
    def port_name(self):
        """返回当前连接的串口名称或 WebSocket 地址。"""
        return self.serial.port if self.serial is not None else None

    def _is_usb_esp32_s3(self):
        """判断当前连接是否为 ESP32-S3 的 USB 控制台传输。"""
        if self.websocket_url or isinstance(self.serial, WebSocketDevice):
            return False
        normalized = str(self.board_model or "").strip().lower().replace("_", "-")
        return normalized in ("esp32-s3", "esp32s3")

    def _serial_write_profile(self):
        """返回当前设备适用的主机写入块大小和块间让步时间。"""
        if self._is_usb_esp32_s3():
            return (
                ESP32_S3_SERIAL_WRITE_CHUNK_SIZE,
                ESP32_S3_SERIAL_WRITE_CHUNK_PAUSE_SECONDS,
            )
        return SERIAL_WRITE_CHUNK_SIZE, 0.0

    def connect(self):
        """优先连接指定 WebSocket，否则枚举串口并通过协议握手识别设备。"""
        if self.websocket_url:
            self._connect_websocket()
            return
        if self.configured_port:
            candidates = [self.configured_port]
        else:
            # 复合 USB 设备中自定义数据 CDC 的接口序号高于内置
            # REPL CDC；优先探测高序号接口，仍以 PONG 作为最终判据。
            ports = list(list_ports.comports())
            ports.sort(
                key=lambda item: (item.location or "", item.device),
                reverse=True,
            )
            candidates = [item.device for item in ports]
        if not self.configured_port and len(candidates) > 1:
            self._connect_parallel(candidates)
            return
        LOGGER.debug("[串口发现] 候选端口：%s", ", ".join(candidates) if candidates else "无")
        errors = []
        for port in candidates:
            if self.cancellation_event is not None and self.cancellation_event.is_set():
                raise RuntimeError("设备探测已取消")
            try:
                LOGGER.debug("[串口打开] 正在打开 %s，波特率 115200", port)
                device = serial.Serial(port, 115200, timeout=0.3, write_timeout=10)
                if self.cancellation_event is None:
                    time.sleep(1.0)
                elif self.cancellation_event.wait(1.0):
                    device.close()
                    raise RuntimeError("设备探测已取消")
                device.reset_input_buffer()
                device.reset_output_buffer()
                if self._handshake(device):
                    self.serial = device
                    LOGGER.info(
                        "[串口连接] %s 握手成功：开发板=%s，LCD=%s，屏幕方案=%s，固件版本=%s，分辨率=%sx%s，Wi-Fi支持=%s",
                        port,
                        self.board_model or "未知",
                        self.lcd_device_type or "未知",
                        self.screen_color_profile or "未知",
                        self.firmware_version or "未知",
                        self.screen_width or "未知",
                        self.screen_height or "未知",
                        "是" if (self.net_status or {}).get("wifi_enabled") else "否",
                    )
                    self._start_cdc_framework()
                    return
                LOGGER.warning("[串口握手] %s 未返回有效设备标识", port)
                device.close()
            except (OSError, serial.SerialException) as error:
                LOGGER.warning("[串口异常] %s：%s", port, error)
                errors.append(f"{port}: {error}")
        detail = "；".join(errors) if errors else "未发现可用串口"
        raise RuntimeError(f"未找到 Pico LCD：{detail}")

    def _connect_websocket(self):
        """建立 WebSocket 连接，完成 PV1 握手并启动统一读写框架。"""
        device = None
        try:
            LOGGER.info("[WebSocket 连接] 正在连接 %s", self.websocket_url)
            device = WebSocketDevice(self.websocket_url)
            if not self._handshake(device):
                raise RuntimeError("WebSocket 未返回有效设备标识")
            self.serial = device
            self._start_cdc_framework()
            LOGGER.info(
                "[WebSocket 连接] %s 握手成功：开发板=%s，LCD=%s，屏幕方案=%s，固件版本=%s，分辨率=%sx%s，Wi-Fi支持=%s",
                self.websocket_url,
                self.board_model or "未知",
                self.lcd_device_type or "未知",
                self.screen_color_profile or "未知",
                self.firmware_version or "未知",
                self.screen_width or "未知",
                self.screen_height or "未知",
                "是" if (self.net_status or {}).get("wifi_enabled") else "否",
            )
        except Exception:
            if device is not None:
                device.close()
            raise

    def _connect_parallel(self, candidates):
        """并行探测候选串口，并在任一端口成功后中断其余探测。"""
        cancellation_event = threading.Event()

        def probe(port):
            """使用独立客户端探测一个串口，避免并发覆盖握手状态。"""
            client = PicoJsonClient(
                port,
                self.probe_interval,
                cancellation_event=cancellation_event,
            )
            try:
                client.connect()
                return client
            except RuntimeError:
                client.close()
                return None

        executor = ThreadPoolExecutor(
            max_workers=len(candidates), thread_name_prefix="串口探测"
        )
        futures = [executor.submit(probe, port) for port in candidates]
        winner = None
        try:
            for future in as_completed(futures):
                client = future.result()
                if client is None:
                    continue
                winner = client
                cancellation_event.set()
                for pending in futures:
                    if pending is not future:
                        pending.cancel()
                break
        finally:
            cancellation_event.set()
            executor.shutdown(wait=True, cancel_futures=True)
        for future in futures:
            if not future.done() or future.cancelled():
                continue
            client = future.result()
            if client is not None and client is not winner:
                client.close()
        if winner is None:
            raise RuntimeError("未找到 Pico LCD：所有候选串口均未响应")
        self.serial = winner.serial
        winner.serial = None
        self.transport = winner.transport
        winner.transport = None
        if self.transport is not None:
            self.transport.rebind_callbacks(
                response_callback=self._handle_cdc_response,
                error_callback=self._handle_cdc_error,
            )
        self.board_model = winner.board_model
        self.lcd_device_type = winner.lcd_device_type
        self.screen_color_profile = winner.screen_color_profile
        self.firmware_version = winner.firmware_version
        self.screen_width = winner.screen_width
        self.screen_height = winner.screen_height
        self.styles = winner.styles
        self.net_status = winner.net_status
        winner.close()

    def _start_cdc_framework(self):
        """在握手完成后启动适用于 USB CDC 和 WebSocket 的读写线程。"""
        if self.serial is None:
            return
        write_chunk_size, write_chunk_pause_seconds = self._serial_write_profile()
        self.transport = UsbCdcFramework(
            self.serial,
            parse_frame,
            port_name=self.port_name,
            response_callback=self._handle_cdc_response,
            error_callback=self._handle_cdc_error,
            write_chunk_size=write_chunk_size,
            write_chunk_pause_seconds=write_chunk_pause_seconds,
        )
        self.transport.start()

    def _handle_cdc_response(self, label, response, frame):
        """统一记录读线程收到的 Pico 响应，并把致命事件转为重连异常。"""
        received_at = time.monotonic()
        LOGGER.debug(
            "[Pico -> Monitor][%s][%s 响应] %s%s",
            self.port_name,
            label,
            response.decode("utf-8", errors="replace"),
            self._format_json_ack_timing_suffix(frame, received_at),
        )
        self._notify_json_ack(frame)
        if _is_restarting_fatal(frame):
            raise PicoRestartingError("Pico 发生不可恢复的渲染错误，设备正在自动重启")

    def _handle_cdc_error(self, frame):
        """处理读线程提前收到的 ERR 帧，JSON 解析错误只记录不触发断线。"""
        payload = frame[1].decode("utf-8", errors="replace")
        if payload.startswith("BAD_JSON"):
            LOGGER.warning("[JSONZ 异步错误][%s] %s", self.port_name, payload)
            return True
        return False

    @staticmethod
    def available_ports():
        """返回当前系统可见串口的稳定快照。"""
        return frozenset(item.device for item in list_ports.comports())

    def _handshake(self, device):
        """发送设备发现命令并验证 Pico 固件响应。"""
        self.board_model = None
        self.lcd_device_type = None
        self.screen_color_profile = None
        self.firmware_version = None
        self.screen_width = None
        self.screen_height = None
        self.styles = []
        for attempt in range(1, 4):
            if self.cancellation_event is not None and self.cancellation_event.is_set():
                return False
            if attempt > 1:
                if self.cancellation_event is None:
                    time.sleep(self.probe_interval)
                elif self.cancellation_event.wait(self.probe_interval):
                    return False
            LOGGER.debug(
                "[Monitor -> Pico][%s][握手 %d/3][PV1 %d 字节] repr=%r hex=%s",
                device.port,
                attempt,
                len(PING_COMMAND),
                PING_COMMAND,
                PING_COMMAND.hex(" "),
            )
            wire_ping = PING_COMMAND
            written = 0
            while written < len(wire_ping):
                count = device.write(wire_ping[written:])
                if not count:
                    raise serial.SerialTimeoutException(
                        f"握手包仅发送 {written}/{len(wire_ping)} 字节"
                    )
                written += count
            device.flush()
            LOGGER.debug(
                "[Monitor -> Pico][%s][握手 %d/3][实际发送 %d/%d 字节]",
                device.port,
                attempt,
                written,
                len(wire_ping),
            )
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                if self.cancellation_event is not None and self.cancellation_event.is_set():
                    return False
                raw_message = device.readline()
                message = raw_message.decode("utf-8", errors="replace").strip()
                if message:
                    LOGGER.debug("[Pico -> Monitor][%s][握手响应] %s", device.port, message)
                try:
                    frame = parse_frame(raw_message)
                except ValueError as error:
                    LOGGER.warning("[Pico -> Monitor][%s][坏帧] %s", device.port, error)
                    continue
                if frame and frame[0] == "PONG":
                    self._parse_pong_payload(frame[1])
                    return True
        return False

    def _parse_pong_payload(self, payload):
        """解析 PV1 PONG 的 JSON 设备信息。"""
        information = json.loads(payload.decode("utf-8"))
        self.board_model = information.get("board_model") or None
        self.lcd_device_type = information.get("lcd_device_type") or None
        self.screen_color_profile = information.get("screen_color_profile") or None
        self.firmware_version = information.get("firmware_version") or None
        self.screen_width = information.get("width") or None
        self.screen_height = information.get("height") or None
        styles = information.get("styles")
        if isinstance(styles, list):
            self.styles = [item for item in styles if isinstance(item, dict)]
        net_status = information.get("net")
        self.net_status = net_status if isinstance(net_status, dict) else None

    def device_information(self):
        """返回当前已连接 Pico 的硬件配置与固件版本。"""
        information = {
            "board_model": self.board_model,
            "lcd_device_type": self.lcd_device_type,
            "screen_color_profile": self.screen_color_profile,
            "firmware_version": self.firmware_version,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
        }
        if isinstance(self.net_status, dict):
            information["net"] = dict(self.net_status)
        return information

    def _write_packet(self, packet, label, build_elapsed_ms=0.0):
        """按统一分块策略写入一条 PV1 帧，并输出串口写入耗时日志。"""
        if self.transport is not None:
            self.transport.raise_error_if_any()
            packet_bytes = bytes(packet)
            total_chunks = (len(packet_bytes) + SERIAL_WRITE_CHUNK_SIZE - 1) // SERIAL_WRITE_CHUNK_SIZE
            LOGGER.debug(
                "[Monitor -> Pico][%s][%s][发送帧 %d 字节，共 %d 块]",
                self.port_name,
                label,
                len(packet_bytes),
                total_chunks,
            )
            timing = self.transport.write_packet(
                packet_bytes,
                label,
                build_elapsed_ms=build_elapsed_ms,
                timeout=max(1.0, JSON_ACK_TIMEOUT),
            )
            total_elapsed_ms = build_elapsed_ms + timing["send_elapsed_ms"]
            LOGGER.debug(
                "[协议耗时][%s][%s 写入汇总] 构帧=%.1f ms，write合计=%.1f ms，最慢write=%.1f ms，flush=%.1f ms，发送阶段=%.1f ms，总写入=%d/%d 字节，共%d块",
                self.port_name,
                label,
                build_elapsed_ms,
                timing["write_elapsed_ms"],
                timing["slowest_write_ms"],
                timing["flush_elapsed_ms"],
                timing["send_elapsed_ms"],
                timing["total_written"],
                len(packet_bytes),
                timing["chunk_count"],
            )
            if total_elapsed_ms >= SERIAL_SLOW_SEND_WARNING_MS:
                LOGGER.warning(
                    "[协议慢发送][%s][%s] 总耗时=%.1f ms，构帧=%.1f ms，write合计=%.1f ms，最慢write=%.1f ms，flush=%.1f ms，总写入=%d/%d 字节，共%d块",
                    self.port_name,
                    label,
                    total_elapsed_ms,
                    build_elapsed_ms,
                    timing["write_elapsed_ms"],
                    timing["slowest_write_ms"],
                    timing["flush_elapsed_ms"],
                    timing["total_written"],
                    len(packet_bytes),
                    timing["chunk_count"],
                )
            return timing
        packet = memoryview(packet)
        write_chunk_size, write_chunk_pause_seconds = self._serial_write_profile()
        total_chunks = (len(packet) + write_chunk_size - 1) // write_chunk_size
        LOGGER.debug(
            "[Monitor -> Pico][%s][%s][发送帧 %d 字节，共 %d 块]",
            self.port_name,
            label,
            len(packet),
            total_chunks,
        )
        send_started = time.monotonic()
        chunk_count = 0
        write_elapsed_ms = 0.0
        slowest_write_ms = 0.0
        total_written = 0
        for position in range(0, len(packet), write_chunk_size):
            chunk = packet[position:position + write_chunk_size]
            write_started = time.monotonic()
            written = self.serial.write(chunk)
            chunk_elapsed_ms = (time.monotonic() - write_started) * 1000
            write_elapsed_ms += chunk_elapsed_ms
            slowest_write_ms = max(slowest_write_ms, chunk_elapsed_ms)
            chunk_count += 1
            total_written += written or 0
            LOGGER.debug(
                "[协议耗时][%s][%s 写入 %d/%d] offset=%d，请求=%d 字节，实际=%s 字节，耗时=%.1f ms",
                self.port_name,
                label,
                chunk_count,
                total_chunks,
                position,
                len(chunk),
                written,
                chunk_elapsed_ms,
            )
            if written != len(chunk):
                raise serial.SerialTimeoutException(
                    "%s 仅发送 %d/%d 字节，当前块 %d/%d 实际写入 %s/%d 字节" % (
                        label,
                        total_written,
                        len(packet),
                        chunk_count,
                        total_chunks,
                        written,
                        len(chunk),
                    )
                )
            if write_chunk_pause_seconds and position + len(chunk) < len(packet):
                time.sleep(write_chunk_pause_seconds)
        flush_started = time.monotonic()
        self.serial.flush()
        flush_elapsed_ms = (time.monotonic() - flush_started) * 1000
        send_elapsed_ms = (time.monotonic() - send_started) * 1000
        total_elapsed_ms = build_elapsed_ms + send_elapsed_ms
        LOGGER.debug(
            "[协议耗时][%s][%s 写入汇总] 构帧=%.1f ms，write合计=%.1f ms，最慢write=%.1f ms，flush=%.1f ms，发送阶段=%.1f ms，总写入=%d/%d 字节，共%d块",
            self.port_name,
            label,
            build_elapsed_ms,
            write_elapsed_ms,
            slowest_write_ms,
            flush_elapsed_ms,
            send_elapsed_ms,
            total_written,
            len(packet),
            chunk_count,
        )
        if total_elapsed_ms >= SERIAL_SLOW_SEND_WARNING_MS:
            LOGGER.warning(
                "[协议慢发送][%s][%s] 总耗时=%.1f ms，构帧=%.1f ms，write合计=%.1f ms，最慢write=%.1f ms，flush=%.1f ms，总写入=%d/%d 字节，共%d块",
                self.port_name,
                label,
                total_elapsed_ms,
                build_elapsed_ms,
                write_elapsed_ms,
                slowest_write_ms,
                flush_elapsed_ms,
                total_written,
                len(packet),
                chunk_count,
            )
        return {
            "build_elapsed_ms": build_elapsed_ms,
            "send_started": send_started,
            "send_finished": send_started + send_elapsed_ms / 1000,
            "send_elapsed_ms": send_elapsed_ms,
        }

    def _read_protocol_frame(self, label):
        """读取并解析一条 Pico 返回帧，同时输出原始响应日志。"""
        if self.transport is not None:
            return self.transport.read_frame(label, timeout=0.3)
        device = self.serial
        if device is None:
            raise serial.SerialException("Pico 串口已关闭")
        try:
            response = device.readline().strip()
        except TypeError as error:
            # PySerial serialwin32 在其他线程恰好关闭句柄时可能对空的
            # OVERLAPPED 事件执行 ctypes.byref；将其归一化为可重连异常。
            if self.serial is not device or not getattr(device, "is_open", False):
                raise serial.SerialException("读取 Pico 响应时串口已关闭") from error
            raise
        try:
            frame = parse_frame(response)
        except ValueError as error:
            LOGGER.warning(
                "[Pico -> Monitor][%s][%s 坏帧] %s raw=%r",
                self.port_name,
                label,
                error,
                response,
            )
            raise RuntimeError(f"Pico 返回损坏协议帧：{error}") from error
        if response:
            received_at = time.monotonic()
            LOGGER.debug(
                "[Pico -> Monitor][%s][%s 响应] %s%s",
                self.port_name,
                label,
                response.decode("utf-8", errors="replace"),
                self._format_json_ack_timing_suffix(frame, received_at),
            )
        return frame

    def _wait_command_result(self, request_id, timeout, label, default_error):
        """等待指定 request_id 的 COMMAND 响应，供样式列表和上传命令复用。"""
        wait_started = time.monotonic()
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            frame = self._read_protocol_frame(label)
            if frame and frame[0] == "COMMAND":
                result = json.loads(frame[1].decode("utf-8"))
                if result.get("request_id") != request_id:
                    LOGGER.debug(
                        "[Pico -> Monitor][%s][%s 忽略响应] request_id=%s，期望=%s",
                        self.port_name,
                        label,
                        result.get("request_id"),
                        request_id,
                    )
                    continue
                elapsed_ms = (time.monotonic() - wait_started) * 1000
                if result.get("status") != "ok":
                    LOGGER.warning(
                        "[Pico -> Monitor][%s][%s 失败] 耗时=%.1f ms，结果=%s",
                        self.port_name,
                        label,
                        elapsed_ms,
                        result,
                    )
                    raise RuntimeError(result.get("error") or default_error)
                LOGGER.debug(
                    "[Pico -> Monitor][%s][%s 成功] COMMAND等待=%.1f ms，data=%s",
                    self.port_name,
                    label,
                    elapsed_ms,
                    result.get("data"),
                )
                return result
            if _is_restarting_fatal(frame):
                raise PicoRestartingError(
                    frame[1].decode("utf-8", errors="replace")
                )
            if frame and frame[0] == "ERR":
                raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
        LOGGER.error(
            "[交互超时][%s][%s] %.1f 秒内未收到 COMMAND request_id=%s",
            self.port_name,
            label,
            float(timeout),
            request_id,
        )
        raise RuntimeError(default_error + "：等待 Pico 响应超时")

    def send(self, snapshot, wait_ack=False, ack_timeout=JSON_ACK_TIMEOUT):
        """发送带请求序号的 JSON 快照，并可等待 Pico 确认以形成背压。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        self._drain_json_responses()
        request_id = self._next_json_request_id()
        ack_event = self._register_json_ack_waiter(request_id) if wait_ack else None
        build_started = time.monotonic()
        try:
            packets = self.build_snapshot_packets(snapshot, request_id=request_id)
            build_elapsed_ms = (time.monotonic() - build_started) * 1000
            for index, packet in enumerate(packets):
                is_final_packet = index == len(packets) - 1
                label = "JSONZ#{}".format(request_id)
                if len(packets) > 1:
                    label = "{}.{}/{}".format(label, index + 1, len(packets))
                if is_final_packet:
                    self._begin_json_ack_timing(request_id, build_started, build_elapsed_ms)
                write_timing = self._write_packet(packet, label, build_elapsed_ms)
                if is_final_packet:
                    self._complete_json_ack_timing(request_id, build_started, write_timing)
            if wait_ack:
                self._wait_json_ack(request_id, ack_event, ack_timeout)
        finally:
            if wait_ack:
                self._remove_json_ack_waiter(request_id)

    def close(self):
        """安全关闭当前传输并恢复为未连接状态。"""
        transport, self.transport = self.transport, None
        if transport is not None:
            transport.close(wait=True)
        device, self.serial = self.serial, None
        if device is not None:
            try:
                LOGGER.info("[串口关闭] 正在关闭 %s", device.port)
                device.close()
            except (OSError, serial.SerialException):
                LOGGER.exception("[串口异常] 关闭 %s 失败", device.port)


REBOOT_COMMAND = PicoJsonClient.build_command_packet("reboot", request_id="reboot")
