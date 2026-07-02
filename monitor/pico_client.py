"""发现 Pico LCD，并通过 USB 串口可靠发送 JSON 系统快照。"""

import json
import logging
import time

import serial
from serial.tools import list_ports


PING_COMMAND = b"PING:PICO_LCD?\n"
JSON_ACK = b"ACK:JSON"
LOGGER = logging.getLogger("pico-monitor.serial")


class PicoJsonClient:
    """封装 Pico LCD 自动发现、握手、数据发送和连接清理。"""

    def __init__(self, configured_port=None):
        """保存可选固定串口名称并初始化断开状态。"""
        self.configured_port = configured_port
        self.serial = None

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
                    LOGGER.info("[串口连接] %s 握手成功", port)
                    return
                LOGGER.warning("[串口握手] %s 未返回有效设备标识", port)
                device.close()
            except (OSError, serial.SerialException) as error:
                LOGGER.warning("[串口异常] %s：%s", port, error)
                errors.append(f"{port}: {error}")
        detail = "；".join(errors) if errors else "未发现可用串口"
        raise RuntimeError(f"未找到 Pico LCD：{detail}")

    @staticmethod
    def _handshake(device):
        """发送设备发现命令并验证 Pico 固件响应。"""
        for attempt in range(1, 4):
            LOGGER.info("[Monitor -> Pico][%s][握手 %d/3] %s", device.port, attempt, PING_COMMAND.decode("ascii").strip())
            device.write(PING_COMMAND)
            device.flush()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                message = device.readline().decode("utf-8", errors="replace").strip()
                if message:
                    LOGGER.info("[Pico -> Monitor][%s][握手响应] %s", device.port, message)
                if message == "BOOT:PICO_LCD_READY" or message.startswith("PONG:PICO_LCD:") or message.startswith("ACK:LCD_FRAME:"):
                    return True
        return False

    @staticmethod
    def build_packet(snapshot):
        """将系统快照编码为与 Pico 串口协议完全一致的 JSON 数据包。"""
        payload = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return b"JSON:" + payload + b"\n"

    def send(self, snapshot):
        """分块发送单行 JSON 数据，并等待 Pico 返回接收确认。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        packet = memoryview(self.build_packet(snapshot))
        LOGGER.info("[Monitor -> Pico][%s][JSON][%d 字节] %s", self.port_name, len(packet), bytes(packet).decode("utf-8", errors="replace").rstrip())
        chunk_count = 0
        for position in range(0, len(packet), 64):
            self.serial.write(packet[position:position + 64])
            chunk_count += 1
        self.serial.flush()
        LOGGER.info("[Monitor -> Pico][%s][发送完成] 共 %d 个数据块", self.port_name, chunk_count)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            response = self.serial.readline().strip()
            if response:
                LOGGER.info("[Pico -> Monitor][%s][响应] %s", self.port_name, response.decode("utf-8", errors="replace"))
            if response == JSON_ACK:
                LOGGER.info("[交互完成][%s] Pico 已确认本次 JSON", self.port_name)
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
