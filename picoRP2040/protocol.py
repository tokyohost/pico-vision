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
    BOARD_MODEL,
    DEVICE_NAME,
    FIRMWARE_VERSION,
    HEIGHT,
    JSON_PREFIX,
    LCD_DRIVER,
    MAX_JSON_SIZE,
    MAX_UPGRADE_LINE_SIZE,
    PING_TEXT,
    PIXEL_FORMAT,
    SCREEN_COLOR_PROFILE,
    SERIAL_READ_CHUNK_SIZE,
    SERIAL_READ_BUDGET,
    UPGRADE_PREFIX,
    WIDTH,
)


class JsonProtocol:
    """增量接收 ASCII 行，避免二进制控制字节触发 MicroPython 中断。"""

    def __init__(self, upgrade_manager=None):
        """初始化标准输入输出、轮询器和行缓冲区。"""
        self._input = sys.stdin
        self._reader = getattr(sys.stdin, "buffer", sys.stdin)
        self._output = getattr(sys.stdout, "buffer", sys.stdout)
        self._poller = select.poll()
        # RP2 的 USB REPL 在 sys.stdin 上实现流轮询接口；部分固件的
        # sys.stdin.buffer 虽可非阻塞读取，却不会正确报告 POLLIN 可读事件。
        # 因此轮询文本流、读取二进制流，兼顾 Linux CDC 与 Windows 串口行为。
        self._poller.register(self._input, select.POLLIN)
        self._buffer = bytearray()
        self._read_buffer = bytearray(SERIAL_READ_CHUNK_SIZE)
        self._upgrade_manager = upgrade_manager

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
            # readinto() 按非阻塞流语义返回当前可用字节数，并复用固定缓冲区，
            # 避免 read(n) 在 Linux USB CDC 下等待凑满 n 字节及反复分配对象。
            received = self._reader.readinto(self._read_buffer)
            if not received:
                break
            self._buffer.extend(memoryview(self._read_buffer)[:received])
            read_count += received
            maximum_size = max(MAX_JSON_SIZE + len(JSON_PREFIX) + 1, MAX_UPGRADE_LINE_SIZE)
            if len(self._buffer) > maximum_size:
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
            # memoryview 避免 bytearray 切片先复制一次整包数据，降低解析峰值内存。
            line_view = memoryview(self._buffer)[:newline]
            line = bytes(line_view)
            del line_view
            self._consume(newline + 1)
            if line.startswith(JSON_PREFIX):
                payload = line[len(JSON_PREFIX):]
                try:
                    latest = json.loads(payload.decode("utf-8"))
                    self.write(b"ACK:JSON\n")
                except (ValueError, UnicodeError):
                    self.write(b"ERR:BAD_JSON\n")
                continue
            line = line.strip()
            if line == PING_TEXT:
                self._write_pong()
                continue
            if line.startswith(UPGRADE_PREFIX):
                if self._upgrade_manager is None:
                    self.write(b"ERR:UPGRADE_UNAVAILABLE\n")
                else:
                    self._upgrade_manager.handle(line[len(UPGRADE_PREFIX):])
                continue
        return latest

    def _consume(self, count):
        """重建剩余缓冲区以兼容 RP2040 MicroPython。"""
        if count >= len(self._buffer):
            self._buffer = bytearray()
        else:
            self._buffer = bytearray(self._buffer[count:])

    def _write_pong(self):
        """返回设备能力、硬件型号、屏幕方案及固件版本。"""
        response = (
            "PONG:{}:{}:{}x{}:{}:BOARD={}:SCREEN={}:VERSION={}:JSON\n"
        ).format(
            DEVICE_NAME,
            LCD_DRIVER,
            WIDTH,
            HEIGHT,
            PIXEL_FORMAT,
            BOARD_MODEL,
            SCREEN_COLOR_PROFILE,
            FIRMWARE_VERSION,
        )
        self.write(response.encode())
