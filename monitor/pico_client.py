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


SERIAL_PROTOCOL_BLOCK_SIZE = 64
PING_COMMAND = b"PING:PICO_LCD?".ljust(
    SERIAL_PROTOCOL_BLOCK_SIZE - 1, b" "
) + b"\n"
JSON_ACK = b"ACK:JSON"
BAD_JSON_ERROR = b"ERR:BAD_JSON"
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

    def _handshake(self, device):
        """发送设备发现命令并验证 Pico 固件响应。"""
        self.board_model = None
        self.screen_color_profile = None
        self.firmware_version = None
        legacy_response_received = False
        for attempt in range(1, 4):
            LOGGER.info("[Monitor -> Pico][%s][握手 %d/3] %s", device.port, attempt, PING_COMMAND.decode("ascii").strip())
            device.write(PING_COMMAND)
            device.flush()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                message = device.readline().decode("utf-8", errors="replace").strip()
                if message:
                    LOGGER.info("[Pico -> Monitor][%s][握手响应] %s", device.port, message)
                if message.startswith("PONG:PICO_LCD:"):
                    self._parse_pong(message)
                    return True
                if message == "BOOT:PICO_LCD_READY" or message.startswith("ACK:LCD_FRAME:"):
                    legacy_response_received = True
        return legacy_response_received

    def _parse_pong(self, message):
        """解析新版握手中的开发板、屏幕方案和固件版本字段。"""
        fields = {}
        for part in message.split(":"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            fields[name.strip().upper()] = value.strip()
        self.board_model = fields.get("BOARD") or None
        self.screen_color_profile = fields.get("SCREEN") or None
        self.firmware_version = fields.get("VERSION") or None

    def device_information(self):
        """返回当前已连接 Pico 的硬件配置与固件版本。"""
        return {
            "board_model": self.board_model,
            "screen_color_profile": self.screen_color_profile,
            "firmware_version": self.firmware_version,
        }

    @staticmethod
    def build_packet(snapshot):
        """编码 JSON 并补齐协议块，支持 Pico 批量读取且不阻塞尾块。"""
        payload = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        line = b"JSON:" + payload
        padding_size = -(len(line) + 1) % SERIAL_PROTOCOL_BLOCK_SIZE
        return line + b" " * padding_size + b"\n"

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
            if response == JSON_ACK:
                LOGGER.info("[交互完成][%s] Pico 已确认本次 JSON", self.port_name)
                return
            if response == BAD_JSON_ERROR:
                LOGGER.warning(
                    "[数据帧丢弃][%s] Pico 无法解析本次 JSON，保持串口连接并等待下一帧",
                    self.port_name,
                )
                return
            if response.startswith((b"ERR:", b"FATAL:")):
                raise RuntimeError(response.decode("utf-8", errors="replace"))
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
