"""负责发现 Pico LCD 并通过 USB 串口发送 JSON 快照。"""

import json
import struct
import time

import serial
from serial.tools import list_ports


PING_COMMAND = b"PING:PICO_LCD?\n"
EXPECTED_PREFIX = "PONG:PICO_LCD:"
JSON_MAGIC = b"JSN0"
SERIAL_BAUDRATE = 115200


class PicoJsonClient:
    """发现 Pico LCD 串口设备并发送长度前缀 JSON 数据包。"""

    def __init__(self, configured_port=None):
        """保存可选固定串口，连接将在首次调用时建立。"""
        self.configured_port = configured_port
        self.serial = None

    def connect(self):
        """连接指定串口或通过握手自动发现 Pico LCD。"""
        candidates = (
            [self.configured_port]
            if self.configured_port
            else [item.device for item in list_ports.comports()]
        )
        for port in candidates:
            device = self._try_port(port)
            if device is not None:
                self.serial = device
                print("已连接 Pico LCD：{}".format(port))
                return
        raise RuntimeError("未找到 Pico LCD，请确认 main.py 已在 Pico 运行且串口未被占用。")

    @staticmethod
    def _try_port(port):
        """打开单个串口并通过文本握手验证设备身份。"""
        try:
            device = serial.Serial(
                port,
                SERIAL_BAUDRATE,
                timeout=0.3,
                write_timeout=2,
            )
            time.sleep(1.5)
            device.reset_input_buffer()
            device.reset_output_buffer()
            for _ in range(3):
                device.write(PING_COMMAND)
                device.flush()
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    line = device.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith(EXPECTED_PREFIX) and line.endswith(":JSON"):
                        return device
            device.close()
        except (OSError, serial.SerialException):
            return None
        return None

    def send(self, snapshot):
        """将系统快照编码为紧凑 UTF-8 JSON 后发送给 Pico。"""
        if self.serial is None:
            raise RuntimeError("Pico 串口尚未连接。")
        payload = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        packet = JSON_MAGIC + struct.pack(">I", len(payload)) + payload
        self.serial.write(packet)
        self.serial.flush()

    def close(self):
        """安全关闭当前串口连接。"""
        if self.serial is not None:
            self.serial.close()
            self.serial = None
