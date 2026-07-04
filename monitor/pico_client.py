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



"""发现 Pico LCD，并通过 USB 串口可靠发送 JSON 系统快照。"""


import json
import logging
import time

import serial
from serial.tools import list_ports


FRAME_MAGIC = b"PV1"
FRAME_MAX_PAYLOAD = 16 * 1024


def crc16_ccitt(data):
    """计算协议帧使用的 CRC-16/CCITT-FALSE。"""
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_frame(message_type, payload=b""):
    """构建 PV1:type:length:crc:payload 帧。"""
    kind = message_type.encode("ascii") if isinstance(message_type, str) else bytes(message_type)
    payload = bytes(payload)
    checksum = crc16_ccitt(kind + b":" + payload)
    line = b":".join((FRAME_MAGIC, kind, str(len(payload)).encode("ascii"), f"{checksum:04X}".encode("ascii"), payload))
    return line + b"\n"


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
    if trailer:
        raise ValueError("BAD_FRAME_TRAILER")
    if crc16_ccitt(kind + b":" + payload) != expected_crc:
        raise ValueError("BAD_FRAME_CRC")
    return kind.decode("ascii"), payload


PING_COMMAND = build_frame("PING")
SERIAL_WRITE_CHUNK_SIZE = 512
LOGGER = logging.getLogger("pico-monitor.serial")


class PicoJsonClient:
    """封装 Pico LCD 自动发现、握手、数据发送和连接清理。"""

    def __init__(self, configured_port=None):
        """保存可选固定串口名称并初始化断开状态。"""
        self.configured_port = configured_port
        self.serial = None
        self.board_model = None
        self.screen_color_profile = None
        self.firmware_version = None

    @property
    def is_connected(self):
        """返回当前串口是否已经打开。"""
        return self.serial is not None and self.serial.is_open

    @property
    def port_name(self):
        """返回当前连接的串口名称。"""
        return self.serial.port if self.serial is not None else None

    def connect(self):
        """连接固定串口，或枚举所有串口并通过协议握手识别设备。"""
        candidates = [self.configured_port] if self.configured_port else [item.device for item in list_ports.comports()]
        LOGGER.info("[串口发现] 候选端口：%s", ", ".join(candidates) if candidates else "无")
        errors = []
        for port in candidates:
            try:
                LOGGER.info("[串口打开] 正在打开 %s，波特率 115200", port)
                device = serial.Serial(port, 115200, timeout=0.3, write_timeout=10)
                time.sleep(1.0)
                device.reset_output_buffer()
                if self._handshake(device):
                    self.serial = device
                    LOGGER.info(
                        "[串口连接] %s 握手成功：开发板=%s，屏幕方案=%s，固件版本=%s",
                        port,
                        self.board_model or "未知",
                        self.screen_color_profile or "未知",
                        self.firmware_version or "未知",
                    )
                    return
                LOGGER.warning("[串口握手] %s 未返回有效设备标识", port)
                device.close()
            except (OSError, serial.SerialException) as error:
                LOGGER.warning("[串口异常] %s：%s", port, error)
                errors.append(f"{port}: {error}")
        detail = "；".join(errors) if errors else "未发现可用串口"
        raise RuntimeError(f"未找到 Pico LCD：{detail}")

    @staticmethod
    def available_ports():
        """返回当前系统可见串口的稳定快照。"""
        return frozenset(item.device for item in list_ports.comports())

    def _handshake(self, device):
        """发送设备发现命令并验证 Pico 固件响应。"""
        self.board_model = None
        self.screen_color_profile = None
        self.firmware_version = None
        for attempt in range(1, 4):
            LOGGER.info(
                "[Monitor -> Pico][%s][握手 %d/3][PV1 %d 字节] repr=%r hex=%s",
                device.port,
                attempt,
                len(PING_COMMAND),
                PING_COMMAND,
                PING_COMMAND.hex(" "),
            )
            written = 0
            while written < len(PING_COMMAND):
                count = device.write(PING_COMMAND[written:])
                if not count:
                    raise serial.SerialTimeoutException(
                        f"握手包仅发送 {written}/{len(PING_COMMAND)} 字节"
                    )
                written += count
            device.flush()
            LOGGER.info(
                "[Monitor -> Pico][%s][握手 %d/3][实际发送 %d/%d 字节]",
                device.port,
                attempt,
                written,
                len(PING_COMMAND),
            )
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                raw_message = device.readline()
                message = raw_message.decode("utf-8", errors="replace").strip()
                if message:
                    LOGGER.info("[Pico -> Monitor][%s][握手响应] %s", device.port, message)
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
        self.screen_color_profile = information.get("screen_color_profile") or None
        self.firmware_version = information.get("firmware_version") or None

    def device_information(self):
        """返回当前已连接 Pico 的硬件配置与固件版本。"""
        return {
            "board_model": self.board_model,
            "screen_color_profile": self.screen_color_profile,
            "firmware_version": self.firmware_version,
        }

    @staticmethod
    def build_packet(snapshot):
        """把 JSON 编码为带长度与 CRC 的 PV1 数据帧。"""
        payload = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return build_frame("JSON", payload)

    def send(self, snapshot):
        """分块发送单行 JSON 数据，并等待 Pico 返回接收确认。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        packet = memoryview(self.build_packet(snapshot))
        LOGGER.info("[Monitor -> Pico][%s][JSON][%d 字节] %s", self.port_name, len(packet), bytes(packet).decode("utf-8", errors="replace").rstrip())
        send_started = time.monotonic()
        chunk_count = 0
        for position in range(0, len(packet), SERIAL_WRITE_CHUNK_SIZE):
            self.serial.write(
                packet[position:position + SERIAL_WRITE_CHUNK_SIZE]
            )
            chunk_count += 1
        self.serial.flush()
        send_elapsed_ms = (time.monotonic() - send_started) * 1000
        LOGGER.info(
            "[Monitor -> Pico][%s][发送完成] 共 %d 个数据块，耗时 %.1f ms",
            self.port_name,
            chunk_count,
            send_elapsed_ms,
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            response = self.serial.readline().strip()
            if response:
                LOGGER.info("[Pico -> Monitor][%s][响应] %s", self.port_name, response.decode("utf-8", errors="replace"))
            try:
                frame = parse_frame(response)
            except ValueError as error:
                raise RuntimeError(f"Pico 返回损坏协议帧：{error}") from error
            if frame == ("ACK", b"JSON"):
                LOGGER.info("[交互完成][%s] Pico 已确认本次 JSON", self.port_name)
                return
            if frame == ("ERR", b"BAD_JSON"):
                LOGGER.warning(
                    "[数据帧丢弃][%s] Pico 无法解析本次 JSON，保持串口连接并等待下一帧",
                    self.port_name,
                )
                return
            if frame and frame[0] == "ERR":
                raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
        LOGGER.error("[交互超时][%s] 5 秒内未收到 ACK:JSON", self.port_name)
        raise RuntimeError("等待 Pico JSON 接收确认超时")

    def close(self):
        """安全关闭串口，并恢复为未连接状态。"""
        device, self.serial = self.serial, None
        if device is not None:
            try:
                LOGGER.info("[串口关闭] 正在关闭 %s", device.port)
                device.close()
            except (OSError, serial.SerialException):
                LOGGER.exception("[串口异常] 关闭 %s 失败", device.port)
