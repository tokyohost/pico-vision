"""负责发现 Pico LCD 并通过 USB 串口发送 JSON 快照。"""

import json
import time

import serial
from serial.tools import list_ports


PING_COMMAND = b"PING:PICO_LCD?\n"
EXPECTED_PREFIX = "PONG:PICO_LCD:"
JSON_PREFIX = b"JSON:"
SERIAL_BAUDRATE = 115200
SERIAL_WRITE_TIMEOUT_SECONDS = 10
SERIAL_WRITE_CHUNK_SIZE = 64
JSON_ACK_TIMEOUT_SECONDS = 5
JSON_ACK = b"ACK:JSON"


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
        diagnostics = []
        for port in candidates:
            device, messages = self._try_port(port)
            diagnostics.extend("{}: {}".format(port, item) for item in messages)
            if device is not None:
                self.serial = device
                print("已连接 Pico LCD：{}".format(port))
                for message in messages:
                    self._print_pico_log(message)
                return
        detail = "\nPico 输出：\n" + "\n".join(diagnostics) if diagnostics else ""
        raise RuntimeError(
            "未找到 Pico LCD，请确认 main.py 已在 Pico 运行且串口未被占用。" + detail
        )

    @staticmethod
    def _try_port(port):
        """打开单个串口并通过文本握手验证设备身份。"""
        messages = []
        try:
            device = serial.Serial(
                port,
                SERIAL_BAUDRATE,
                timeout=0.3,
                write_timeout=SERIAL_WRITE_TIMEOUT_SECONDS,
            )
            time.sleep(1)
            device.reset_output_buffer()
            for _ in range(3):
                device.write(PING_COMMAND)
                device.flush()
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    line = device.readline().decode("utf-8", errors="replace").strip()
                    if line and line not in messages:
                        messages.append(line)
                    if line.startswith(EXPECTED_PREFIX) and line.endswith(":JSON"):
                        return device, messages
            device.close()
        except (OSError, serial.SerialException) as error:
            messages.append("串口异常：{}".format(error))
        return None, messages

    def send(self, snapshot):
        """分块发送紧凑 JSON 数据包，并等待 Pico 返回接收确认。"""
        if self.serial is None:
            raise RuntimeError("Pico 串口尚未连接。")
        self._drain_logs()
        payload = json.dumps(
            snapshot,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        packet = JSON_PREFIX + payload + b"\n"
        self._write_packet(packet)
        self.serial.flush()
        self._wait_for_ack()

    def _write_packet(self, packet):
        """将数据包拆成 USB 全速端点友好的小块依次写入。"""
        view = memoryview(packet)
        position = 0
        while position < len(packet):
            end = min(position + SERIAL_WRITE_CHUNK_SIZE, len(packet))
            written = self.serial.write(view[position:end])
            if not written:
                raise serial.SerialTimeoutException("Pico 串口未接收任何数据")
            position += written

    def _wait_for_ack(self):
        """等待 Pico 确认 JSON 已完整接收并成功解析。"""
        deadline = time.monotonic() + JSON_ACK_TIMEOUT_SECONDS
        diagnostics = []
        while time.monotonic() < deadline:
            response = self.serial.readline().strip()
            if response:
                self._print_pico_log(
                    response.decode("utf-8", errors="replace")
                )
            if response == JSON_ACK:
                return
            if response.startswith(b"ACK:LCD_FRAME:"):
                continue
            if response.startswith(b"FATAL:"):
                raise RuntimeError(
                    "Pico 运行异常：{}".format(
                        response.decode("utf-8", errors="replace")
                    )
                )
            if response.startswith(b"ERR:"):
                raise RuntimeError("Pico 拒绝 JSON 数据：{}".format(
                    response.decode("utf-8", errors="replace")
                ))
            if response:
                diagnostics.append(response.decode("utf-8", errors="replace"))
        detail = "；Pico 输出：" + " | ".join(diagnostics) if diagnostics else ""
        raise serial.SerialTimeoutException("等待 Pico JSON 接收确认超时" + detail)

    def _drain_logs(self):
        """发送数据前打印串口中尚未读取的全部 Pico 日志。"""
        while self.serial is not None and self.serial.in_waiting > 0:
            response = self.serial.readline().strip()
            if response:
                self._print_pico_log(
                    response.decode("utf-8", errors="replace")
                )

    def _print_pico_log(self, message):
        """使用统一前缀将 Pico 串口输出显示在电脑终端。"""
        port = self.serial.port if self.serial is not None else "PICO"
        print("[PICO {}] {}".format(port, message))

    def close(self):
        """安全关闭当前串口连接。"""
        if self.serial is not None:
            self.serial.close()
            self.serial = None
