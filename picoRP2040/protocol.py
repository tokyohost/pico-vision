"""实现基于纯 ASCII 行的 USB 串口握手与 JSON 接收协议。"""

import sys

try:
    import uselect as select
except ImportError:
    import select

try:
    import ujson as json
except ImportError:
    import json

from config import (
    DEVICE_NAME,
    HEIGHT,
    JSON_PREFIX,
    LCD_DRIVER,
    MAX_JSON_SIZE,
    PING_TEXT,
    PIXEL_FORMAT,
    SERIAL_READ_BUDGET,
    WIDTH,
)


class JsonProtocol:
    """增量接收 ASCII 行，避免二进制控制字节触发 MicroPython 中断。"""

    def __init__(self):
        """初始化标准输入输出、轮询器和行缓冲区。"""
        self._input = sys.stdin
        self._output = getattr(sys.stdout, "buffer", sys.stdout)
        self._poller = select.poll()
        # RP2 的 USB REPL 在 sys.stdin 上实现流轮询接口；部分固件的
        # sys.stdin.buffer 虽可读取，却不会正确报告 POLLIN 可读事件。
        self._poller.register(self._input, select.POLLIN)
        self._buffer = bytearray()

    def write(self, data):
        """向 USB 串口写入响应并尽可能立即刷新。"""
        try:
            self._output.write(data)
        except TypeError:
            self._output.write(data.decode("ascii"))
        try:
            self._output.flush()
        except Exception:
            pass

    def poll(self):
        """在固定读取预算内接收数据并返回最新完整 JSON 对象。"""
        read_count = 0
        while read_count < SERIAL_READ_BUDGET and self._poller.poll(0):
            # 每次只读取一个字符，避免部分 RP2 固件等待凑满请求长度。
            chunk = self._input.read(1)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("ascii")
            self._buffer.extend(chunk)
            read_count += len(chunk)
            if len(self._buffer) > MAX_JSON_SIZE + len(JSON_PREFIX) + 1:
                self._buffer = bytearray()
                self.write(b"ERR:BAD_JSON_SIZE\n")
                return None
        return self._parse_lines()

    def is_busy(self):
        """判断串口是否有待接收字节或未完成的行。"""
        return bool(self._buffer) or bool(self._poller.poll(0))

    def _parse_lines(self):
        """依次解析已完整接收的命令行，并保留最后一个 JSON。"""
        latest = None
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._buffer[:newline]).strip()
            self._consume(newline + 1)
            if line == PING_TEXT:
                self._write_pong()
                continue
            if not line.startswith(JSON_PREFIX):
                continue
            payload = line[len(JSON_PREFIX):]
            try:
                latest = json.loads(payload.decode("utf-8"))
                self.write(b"ACK:JSON\n")
            except (ValueError, UnicodeError):
                self.write(b"ERR:BAD_JSON\n")
        return latest

    def _consume(self, count):
        """重建剩余缓冲区以兼容 RP2040 MicroPython。"""
        if count >= len(self._buffer):
            self._buffer = bytearray()
        else:
            self._buffer = bytearray(self._buffer[count:])

    def _write_pong(self):
        """返回包含设备与屏幕能力的握手响应。"""
        response = "PONG:{}:{}:{}x{}:{}:JSON\n".format(
            DEVICE_NAME, LCD_DRIVER, WIDTH, HEIGHT, PIXEL_FORMAT
        )
        self.write(response.encode())
