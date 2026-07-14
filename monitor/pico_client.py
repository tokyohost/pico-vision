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
import zlib
import base64
import threading
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed

import serial
from serial.tools import list_ports

from json_ack_timing_cache import ExpiringJsonAckTimingCache
from net import WebSocketDevice
from usbCdcFramework import UsbCdcFramework


FRAME_MAGIC = b"PV1"
FRAME_MAX_PAYLOAD = 16 * 1024
TRANSPORT_BLOCK_SIZE = 64
ZLIB_WINDOW_BITS = 9
STYLE_UPLOAD_CHUNK_SIZE = 512
SNAPSHOT_JSON_CHUNK_SIZE = 4 * 1024
JSON_ACK_TIMEOUT = 8.0
JSON_PROGRESS_GRACE_SECONDS = 2.0
SERIAL_SLOW_SEND_WARNING_MS = 200.0


def _build_crc16_byte_table():
    """生成 CRC-16/CCITT 的字节查找表。"""
    table = []
    for value in range(256):
        crc = value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return array("H", table)


CRC16_BYTE_TABLE = _build_crc16_byte_table()


def crc16_ccitt(data):
    """使用字节查表计算 CRC-16/CCITT-FALSE。"""
    crc = 0xFFFF
    for value in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_BYTE_TABLE[((crc >> 8) ^ value) & 0xFF]
    return crc


def build_frame(message_type, payload=b""):
    """构建 PV1:type:length:crc:payload 帧。"""
    kind = message_type.encode("ascii") if isinstance(message_type, str) else bytes(message_type)
    payload = bytes(payload)
    checksum = crc16_ccitt(kind + b":" + payload)
    line = b":".join((FRAME_MAGIC, kind, str(len(payload)).encode("ascii"), f"{checksum:04X}".encode("ascii"), payload))
    padding = -(len(line) + 1) % TRANSPORT_BLOCK_SIZE
    return line + b" " * padding + b"\n"


def parse_frame(line):
    """校验并解析一条 PV1 帧；非 PV1 行返回 None。"""
    line = bytes(line).rstrip(b"\r\n")
    if not line.startswith(FRAME_MAGIC + b":"):
        return None
    parts = line.split(b":", 4)
    if len(parts) != 5:
        raise ValueError("BAD_FRAME_HEADER")
    _, kind, length_text, checksum_text, remainder = parts
    try:
        length = int(length_text)
        expected_crc = int(checksum_text, 16)
    except ValueError as error:
        raise ValueError("BAD_FRAME_HEADER") from error
    if length < 0 or length > FRAME_MAX_PAYLOAD or len(remainder) < length:
        raise ValueError("BAD_FRAME_LENGTH")
    payload, trailer = remainder[:length], remainder[length:]
    if trailer.strip(b" "):
        raise ValueError("BAD_FRAME_TRAILER")
    if crc16_ccitt(kind + b":" + payload) != expected_crc:
        raise ValueError("BAD_FRAME_CRC")
    return kind.decode("ascii"), payload


PING_COMMAND = build_frame("PING")
SERIAL_WRITE_CHUNK_SIZE = 511
ESP32_S3_SERIAL_WRITE_CHUNK_SIZE = 255
ESP32_S3_SERIAL_WRITE_CHUNK_PAUSE_SECONDS = 0.002
LOGGER = logging.getLogger("pico-monitor.serial")
RESTARTING_FATAL_PREFIXES = (
    b"FATAL:MemoryError:",
    "FATAL:ValueError:脏矩形超过画布容量".encode("utf-8"),
)


class PicoRestartingError(RuntimeError):
    """表示 Pico 报告不可恢复错误并正在自动重启。"""


class JsonAckTimeoutError(RuntimeError):
    """表示快照已经发送完成，但未在期限内收到对应 JSON ACK。"""


def _is_restarting_fatal(frame):
    """判断协议帧是否表示 Pico 正在因致命异常自动重启。"""
    return bool(
        frame
        and frame[0] == "EVENT"
        and any(frame[1].startswith(prefix) for prefix in RESTARTING_FATAL_PREFIXES)
    )


class PicoJsonClient:
    """封装 Pico LCD 自动发现、握手、数据发送和连接清理。"""

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

    def request_wifi_list(self, timeout=20.0):
        """请求设备扫描附近 Wi-Fi 并返回网络列表和当前状态。"""
        request_id = "wifi-list-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet("wifi.list", request_id=request_id)
        self._write_packet(packet, "Wi-Fi 搜索")
        return self._wait_command_result(request_id, timeout, "Wi-Fi 搜索", "Wi-Fi 搜索失败")

    def set_wifi(self, ssid, password="", timeout=20.0):
        """请求设备连接指定 Wi-Fi，并返回明确的成功或失败结果。"""
        request_id = "wifi-set-{}".format(int(time.monotonic() * 1000))
        packet = self.build_command_packet(
            "wifi.set",
            params={"ssid": ssid, "password": password, "timeout_ms": int(timeout * 1000)},
            request_id=request_id,
        )
        self._write_packet(packet, "Wi-Fi 连接")
        return self._wait_command_result(request_id, timeout + 2.0, "Wi-Fi 连接", "Wi-Fi 连接失败")

    @staticmethod
    def _wire_snapshot(snapshot):
        """生成实际在线路上传输的快照对象，移除 Pico 端不需要的重复字段。"""
        wire_snapshot = snapshot
        if snapshot.get("physical_disks") is not None and "disks" in snapshot:
            # physical_disks 已包含 Pico 样式所需的磁盘指标；避免在线路上再发送
            # 内容高度重复的逻辑 disks 列表，但不修改采集器持有的原始快照。
            wire_snapshot = dict(snapshot)
            wire_snapshot.pop("disks", None)
        return wire_snapshot

    @staticmethod
    def build_json_payload(snapshot):
        """生成实际在线路上传输的紧凑 JSON 字节串。"""
        return json.dumps(
            PicoJsonClient._wire_snapshot(snapshot),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _snapshot_envelope_payload(snapshot, request_id=None):
        """把快照对象封装为 JSONZ 压缩前的信封字节。"""
        envelope = {
            "mode": "snapshot",
            "data": snapshot,
        }
        if request_id is not None:
            envelope["request_id"] = request_id
        return json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def build_packet(snapshot, request_id=None):
        """把 JSON 编码为带长度与 CRC 的 PV1 数据帧。"""
        payload = PicoJsonClient._snapshot_envelope_payload(
            PicoJsonClient._wire_snapshot(snapshot),
            request_id=request_id,
        )
        return PicoJsonClient._build_jsonz_packet(payload)

    @staticmethod
    def _split_snapshot_payloads(snapshot, request_id=None):
        """按顶层字段把大快照拆成多份小 JSON 信封。"""
        full_payload = PicoJsonClient._snapshot_envelope_payload(
            snapshot,
            request_id=request_id,
        )
        if len(full_payload) <= SNAPSHOT_JSON_CHUNK_SIZE:
            return [full_payload]

        payloads = []
        current = {}
        items = list(snapshot.items())
        total_items = len(items)
        for index, (key, value) in enumerate(items):
            candidate = dict(current)
            candidate[key] = value
            candidate_payload = PicoJsonClient._snapshot_envelope_payload(candidate)
            if current and len(candidate_payload) > SNAPSHOT_JSON_CHUNK_SIZE:
                payloads.append(PicoJsonClient._snapshot_envelope_payload(current))
                current = {key: value}
                continue
            current = candidate
            if index == total_items - 1:
                payloads.append(PicoJsonClient._snapshot_envelope_payload(current))

        if not payloads:
            payloads.append(PicoJsonClient._snapshot_envelope_payload(snapshot))
        if request_id is not None:
            total_payloads = len(payloads)
            for index, payload in enumerate(list(payloads)):
                fragment_snapshot = json.loads(payload.decode("utf-8"))["data"]
                fragment_request_id = request_id
                if index < total_payloads - 1:
                    fragment_request_id = "{}.{}/{}".format(
                        request_id,
                        index + 1,
                        total_payloads,
                    )
                payloads[index] = PicoJsonClient._snapshot_envelope_payload(
                    fragment_snapshot,
                    request_id=fragment_request_id,
                )
        return payloads

    @staticmethod
    def build_snapshot_packets(snapshot, request_id=None):
        """构建一份快照对应的一条或多条 JSONZ 帧。"""
        wire_snapshot = PicoJsonClient._wire_snapshot(snapshot)
        return [
            PicoJsonClient._build_jsonz_packet(payload)
            for payload in PicoJsonClient._split_snapshot_payloads(
                wire_snapshot,
                request_id=request_id,
            )
        ]

    def _next_json_request_id(self):
        """生成进程内单调递增的 JSON 快照请求序号。"""
        self._json_request_sequence = (self._json_request_sequence + 1) & 0x7FFFFFFF
        return self._json_request_sequence

    def _begin_json_ack_timing(self, request_id, build_started, build_elapsed_ms):
        """在写入前登记请求序号，避免 ACK 读线程先到导致耗时未知。"""
        self._json_ack_pending.put(request_id, {
            "created_at": build_started,
            "build_started": build_started,
            "send_started": time.monotonic(),
            "send_finished": None,
            "build_elapsed_ms": build_elapsed_ms,
            "send_elapsed_ms": 0.0,
        })

    def _complete_json_ack_timing(self, request_id, build_started, write_timing):
        """补全 JSON 快照发送时间，用于异步 ACK 到达时计算端到端耗时。"""
        self._json_ack_pending.update(request_id, {
            "build_started": build_started,
            "send_started": write_timing["send_started"],
            "send_finished": write_timing["send_finished"],
            "build_elapsed_ms": write_timing["build_elapsed_ms"],
            "send_elapsed_ms": write_timing["send_elapsed_ms"],
        })

    def _format_json_ack_timing_suffix(self, frame, received_at):
        """为 JSON ACK 响应日志生成发送到确认的耗时说明。"""
        if not frame or frame[0] != "ACK":
            return ""
        payload = frame[1].decode("ascii", errors="replace")
        if payload != "JSON" and not payload.startswith("JSON:"):
            return ""
        request_id = payload.split(":", 1)[1] if ":" in payload else None
        inferred = False
        if request_id is not None:
            timing = self._json_ack_pending.pop(request_id)
        else:
            request_id, timing = self._json_ack_pending.pop_oldest()
            inferred = timing is not None
        if timing is None:
            pending_snapshot = self._json_ack_pending.snapshot()
            if request_id is None:
                return "，发送到收到ACK耗时=未知，ACK缓存={}".format(pending_snapshot)
            return "，request_id={}，发送到收到ACK耗时=未知，ACK缓存={}".format(
                request_id,
                pending_snapshot,
            )
        send_to_ack_ms = (received_at - timing["send_started"]) * 1000
        build_to_ack_ms = (received_at - timing["build_started"]) * 1000
        request_text = "{}{}".format(request_id, "（推断）" if inferred else "")
        if timing.get("send_finished") is None:
            return (
                "，request_id={}，发送到收到ACK耗时={:.1f} ms，写完到ACK=未知，"
                "构帧到ACK={:.1f} ms，构帧={:.1f} ms，发送阶段=进行中"
            ).format(
                request_text,
                send_to_ack_ms,
                build_to_ack_ms,
                timing["build_elapsed_ms"],
            )
        write_done_to_ack_ms = (received_at - timing["send_finished"]) * 1000
        return (
            "，request_id={}，发送到收到ACK耗时={:.1f} ms，写完到ACK={:.1f} ms，"
            "构帧到ACK={:.1f} ms，构帧={:.1f} ms，发送阶段={:.1f} ms"
        ).format(
            request_text,
            send_to_ack_ms,
            write_done_to_ack_ms,
            build_to_ack_ms,
            timing["build_elapsed_ms"],
            timing["send_elapsed_ms"],
        )

    @staticmethod
    def _json_ack_request_id(frame):
        """从 JSON ACK 帧中解析请求序号；旧固件无序号时返回空值。"""
        if not frame or frame[0] != "ACK":
            return None
        payload = frame[1].decode("ascii", errors="replace")
        if payload == "JSON":
            return None
        if payload.startswith("JSON:"):
            return payload.split(":", 1)[1]
        return None

    def _register_json_ack_waiter(self, request_id):
        """为指定 JSON 请求创建 ACK 等待事件。"""
        event = threading.Event()
        with self._json_ack_lock:
            self._json_ack_events[str(request_id)] = event
        return event

    def _remove_json_ack_waiter(self, request_id):
        """清理指定 JSON 请求的 ACK 等待事件。"""
        with self._json_ack_lock:
            self._json_ack_events.pop(str(request_id), None)

    def _notify_json_ack(self, frame):
        """在 CDC 读线程收到 JSON ACK 时唤醒等待发送线程。"""
        if not frame or frame[0] != "ACK":
            return
        payload = frame[1].decode("ascii", errors="replace")
        if payload != "JSON" and not payload.startswith("JSON:"):
            return
        request_id = self._json_ack_request_id(frame)
        with self._json_ack_lock:
            if request_id is None:
                events = list(self._json_ack_events.values())
            else:
                event = self._json_ack_events.get(str(request_id))
                events = [event] if event is not None else []
        for event in events:
            event.set()

    def _wait_json_ack(self, request_id, event, timeout):
        """等待 Pico 确认指定 JSON 快照，期间持续转交 CDC 后台异常。"""
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            if self.transport is None:
                frame = self._read_protocol_frame("JSONZ ACK")
                if frame and frame[0] == "ACK":
                    ack_request_id = self._json_ack_request_id(frame)
                    if ack_request_id is None or str(ack_request_id) == str(request_id):
                        return
                if _is_restarting_fatal(frame):
                    raise PicoRestartingError(
                        frame[1].decode("utf-8", errors="replace")
                    )
                if frame and frame[0] == "ERR":
                    raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
                continue
            if event.wait(min(0.1, max(0.0, deadline - time.monotonic()))):
                return
            self.transport.raise_error_if_any()
        raise JsonAckTimeoutError(
            "等待 JSON ACK 超时：request_id={}".format(request_id)
        )

    def _drain_json_responses(self):
        """非阻塞消费已经到达的 JSON 响应，避免 ACK 反向缓存持续积压。"""
        if self.transport is not None:
            self.transport.raise_error_if_any()
            while True:
                frame = self.transport.read_frame("JSONZ 异步响应", timeout=0.0)
                if not frame:
                    return
                if frame[0] == "ACK" and frame[1].startswith(b"JSON"):
                    continue
                if frame[0] == "ERR":
                    LOGGER.warning(
                        "[JSONZ 异步错误][%s] %s",
                        self.port_name,
                        frame[1].decode("utf-8", errors="replace"),
                    )
                elif _is_restarting_fatal(frame):
                    raise PicoRestartingError("Pico 发生不可恢复的渲染错误，设备正在自动重启")
            return
        device = self.serial
        while device is not None and getattr(device, "in_waiting", 0) > 0:
            frame = self._read_protocol_frame("JSONZ 异步响应")
            if not frame:
                continue
            if frame[0] == "ACK" and frame[1].startswith(b"JSON"):
                continue
            if frame[0] == "ERR":
                LOGGER.warning(
                    "[JSONZ 异步错误][%s] %s",
                    self.port_name,
                    frame[1].decode("utf-8", errors="replace"),
                )
            elif _is_restarting_fatal(frame):
                raise PicoRestartingError("Pico 发生不可恢复的渲染错误，设备正在自动重启")

    @staticmethod
    def _build_jsonz_packet(payload):
        """压缩 JSON 字节并构建统一的 JSONZ 帧。"""
        # 使用 512 字节 zlib 窗口，避免 RP2040 解压时申请默认的 32KB 连续堆。
        compressor = zlib.compressobj(level=6, wbits=ZLIB_WINDOW_BITS)
        compressed = compressor.compress(payload) + compressor.flush()
        return build_frame("JSONZ", base64.b64encode(compressed))

    @staticmethod
    def build_command_packet(command, params=None, request_id=None):
        """把命令策略名称和参数编码为 JSONZ 命令信封。"""
        message = {
            "mode": "command",
            "command": command,
            "params": params or {},
        }
        if request_id is not None:
            message["request_id"] = request_id
        payload = json.dumps(
            message,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return PicoJsonClient._build_jsonz_packet(payload)

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

    def reboot(self, timeout=30.0):
        """请求 Pico 执行软重启，并在指定秒数内等待设备确认。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        LOGGER.info("[Monitor -> Pico][%s][命令 reboot]", self.port_name)
        packet = self.build_command_packet("reboot", request_id="reboot")
        self._write_packet(packet, "reboot")
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            frame = self._read_protocol_frame("reboot")
            if frame and frame[0] == "COMMAND":
                result = json.loads(frame[1].decode("utf-8"))
                if result.get("command") == "reboot" and result.get("status") == "ok":
                    LOGGER.info("[Pico -> Monitor][%s][命令成功 reboot]", self.port_name)
                    return
            if frame and frame[0] == "ERR":
                raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
        raise RuntimeError("设备无响应，请重新拔插设备注册")

    def screenshot(self, timeout=30.0):
        """请求 Pico 分块返回 LCD 画面，并重组为大端 RGB565 数据。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "screenshot-{}".format(int(time.time() * 1000))
        packet = self.build_command_packet("screenshot", request_id=request_id)
        self._write_packet(packet, "screenshot")
        chunks = {}
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            frame = self._read_protocol_frame("screenshot")
            if not frame or frame[0] != "COMMAND":
                if frame and frame[0] == "ERR":
                    raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
                continue
            result = json.loads(frame[1].decode("utf-8"))
            if result.get("request_id") != request_id:
                continue
            if result.get("status") == "chunk":
                data = result.get("data") or {}
                sequence = int(data["sequence"])
                chunks[sequence] = base64.b64decode(data["pixels"], validate=True)
                continue
            if result.get("status") != "ok":
                raise RuntimeError(result.get("error") or "Pico 截图失败")
            metadata = result.get("data") or {}
            expected_chunks = int(metadata.get("chunks", 0))
            if sorted(chunks) != list(range(expected_chunks)):
                raise RuntimeError("Pico 截图数据不完整")
            pixels = b"".join(chunks[index] for index in range(expected_chunks))
            expected_bytes = int(metadata["width"]) * int(metadata["height"]) * 2
            if len(pixels) != expected_bytes:
                raise RuntimeError("Pico 截图像素长度不正确")
            return metadata, pixels
        raise RuntimeError("等待 Pico 截图响应超时")

    def request_style_catalog_info(self, timeout=5.0):
        """请求 Pico 返回自定义样式清单及 Flash 空间信息。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "style-list-{}".format(int(time.time() * 1000))
        build_started = time.monotonic()
        packet = self.build_command_packet("style.list", request_id=request_id)
        build_elapsed_ms = (time.monotonic() - build_started) * 1000
        LOGGER.info(
            "[样式清单][%s] request_id=%s，命令帧=%d 字节，timeout=%.1f 秒",
            self.port_name,
            request_id,
            len(packet),
            timeout,
        )
        self._write_packet(packet, "style.list", build_elapsed_ms)
        result = self._wait_command_result(
            request_id,
            timeout,
            "style.list",
            "样式清单查询失败",
        )
        data = result.get("data") or {}
        styles = data.get("styles", [])
        flash = data.get("flash") or {}
        return {
            "styles": [item for item in styles if isinstance(item, dict)],
            "flash": {
                "free_bytes": max(0, int(flash.get("free_bytes", 0))),
                "total_bytes": max(0, int(flash.get("total_bytes", 0))),
            },
        }

    def request_style_catalog(self, timeout=5.0):
        """请求 Pico 返回自定义样式清单并保持原有列表返回格式。"""
        return self.request_style_catalog_info(timeout)["styles"]

    def delete_style(self, filename, style_name, timeout=5.0):
        """请求 Pico 删除一个自定义样式文件并重启设备。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        request_id = "style-delete-{}".format(int(time.time() * 1000))
        packet = self.build_command_packet(
            "style.delete",
            params={"filename": filename, "style_name": style_name},
            request_id=request_id,
        )
        self._write_packet(packet, "style.delete")
        result = self._wait_command_result(
            request_id, timeout, "style.delete", "自定义样式删除失败",
        )
        return result.get("data") or {}

    def upload_style(self, filename, style_name, content, timeout=10.0, overwrite=False):
        """把样式源码分块写入 Pico 的 Flash 临时文件并完成校验。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        upload_id = filename
        request_prefix = "style-upload-{}".format(int(time.time() * 1000))
        LOGGER.info(
            "[样式上传][%s] filename=%s，style_name=%s，原始=%d 字节，分块=%d 字节，request_id=%s，timeout=%.1f 秒",
            self.port_name,
            filename,
            style_name,
            len(content),
            STYLE_UPLOAD_CHUNK_SIZE,
            request_prefix,
            timeout,
        )
        begin_result = self._send_style_upload_action(
            request_prefix + "-begin",
            {
                "action": "begin", "filename": filename,
                "style_name": style_name, "size": len(content),
                "overwrite": bool(overwrite),
            },
            timeout,
            "begin",
        )
        del begin_result
        try:
            for sequence, offset in enumerate(range(0, len(content), STYLE_UPLOAD_CHUNK_SIZE)):
                chunk = content[offset:offset + STYLE_UPLOAD_CHUNK_SIZE]
                self._send_style_upload_action(
                    request_prefix + "-data-{}".format(sequence),
                    {
                        "action": "data",
                        "upload_id": upload_id,
                        "sequence": sequence,
                        "content": base64.b64encode(chunk).decode("ascii"),
                    },
                    timeout,
                    "data-{}".format(sequence),
                )
            result = self._send_style_upload_action(
                request_prefix + "-finish",
                {"action": "finish", "upload_id": upload_id},
                timeout,
                "finish",
            )
            return result.get("data") or {}
        except Exception:
            try:
                self._send_style_upload_action(
                    request_prefix + "-abort",
                    {"action": "abort", "upload_id": upload_id},
                    min(timeout, 2.0),
                    "abort",
                )
            except Exception:
                LOGGER.warning("[样式上传][%s] Flash 临时文件清理请求失败", self.port_name)
            raise

    def _send_style_upload_action(self, request_id, params, timeout, action):
        """发送一个低内存占用的样式上传动作并等待 Pico 确认。"""
        build_started = time.monotonic()
        packet = self.build_command_packet("uploadStyle", params=params, request_id=request_id)
        build_elapsed_ms = (time.monotonic() - build_started) * 1000
        label = "uploadStyle." + action
        self._write_packet(packet, label, build_elapsed_ms)
        return self._wait_command_result(
            request_id,
            timeout,
            label,
            "自定义样式上传失败",
        )

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
