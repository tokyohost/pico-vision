"""发现 Pico LCD，并通过 USB 串口可靠发送 JSON 系统快照。"""

import json
import time

import serial
from serial.tools import list_ports


PING_COMMAND = b"PING:PICO_LCD?\n"
JSON_ACK = b"ACK:JSON"


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
        errors = []
        for port in candidates:
            try:
                device = serial.Serial(port, 115200, timeout=0.3, write_timeout=10)
                time.sleep(1.0)
                device.reset_output_buffer()
                if self._handshake(device):
                    self.serial = device
                    return
                device.close()
            except (OSError, serial.SerialException) as error:
                errors.append(f"{port}: {error}")
        detail = "；".join(errors) if errors else "未发现可用串口"
        raise RuntimeError(f"未找到 Pico LCD：{detail}")

    @staticmethod
    def _handshake(device):
        """发送设备发现命令并验证 Pico 固件响应。"""
        for _ in range(3):
            device.write(PING_COMMAND)
            device.flush()
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                message = device.readline().decode("utf-8", errors="replace").strip()
                if message == "BOOT:PICO_LCD_READY" or message.startswith("PONG:PICO_LCD:") or message.startswith("ACK:LCD_FRAME:"):
                    return True
        return False

    def send(self, snapshot):
        """分块发送单行 JSON 数据，并等待 Pico 返回接收确认。"""
        if not self.is_connected:
            raise RuntimeError("Pico 串口尚未连接")
        payload = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        packet = memoryview(b"JSON:" + payload + b"\n")
        for position in range(0, len(packet), 64):
            self.serial.write(packet[position:position + 64])
        self.serial.flush()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            response = self.serial.readline().strip()
            if response == JSON_ACK:
                return
            if response.startswith((b"ERR:", b"FATAL:")):
                raise RuntimeError(response.decode("utf-8", errors="replace"))
        raise RuntimeError("等待 Pico JSON 接收确认超时")

    def close(self):
        """安全关闭串口，并恢复为未连接状态。"""
        device, self.serial = self.serial, None
        if device is not None:
            try:
                device.close()
            except (OSError, serial.SerialException):
                pass
