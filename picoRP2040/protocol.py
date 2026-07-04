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
import time
from array import array

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
    LCD_DRIVER,
    MAX_JSON_SIZE,
    MAX_UPGRADE_LINE_SIZE,
    PIXEL_FORMAT,
    SCREEN_COLOR_PROFILE,
    SERIAL_READ_BUDGET,
    WIDTH,
)


def _build_crc16_byte_table():
    """生成仅占约 512 字节的 CRC-16/CCITT 字节查找表。"""
    table = []
    for value in range(256):
        crc = value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return array("H", table)


CRC16_BYTE_TABLE = _build_crc16_byte_table()


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
        self._read_buffer = bytearray(64)
        self._last_byte_ms = None
        self._frame_started_ms = None
        self._frame_read_calls = 0
        self._upgrade_manager = upgrade_manager

    def _write_raw(self, data):
        """向 USB 串口写入已编码 PV1 帧并立即刷新。"""
        try:
            self._output.write(data)
        except TypeError:
            self._output.write(data.decode("ascii"))
        try:
            self._output.flush()
        except Exception:
            pass

    def write(self, data):
        """把应用诊断消息封装为 PV1 EVENT 帧。"""
        self._write_frame("EVENT", bytes(data).strip())

    def poll(self):
        """在固定读取预算内接收数据并返回最新完整 JSON 对象。"""
        self._expire_partial_frame()
        read_count = 0
        while read_count < SERIAL_READ_BUDGET and self._poller.poll(0):
            # 未同步时逐字节寻找 PV1 魔数；同步后，Monitor 保证每帧按 64
            # 字节传输块补齐，因此可以安全批量读取，避免数千次单字节轮询。
            read_size = 1
            if self._buffer.startswith(b"PV1:"):
                read_size = min(64 - len(self._buffer) % 64, SERIAL_READ_BUDGET - read_count)
            received = self._reader.readinto(memoryview(self._read_buffer)[:read_size])
            if not received:
                break
            self._buffer.extend(memoryview(self._read_buffer)[:received])
            self._last_byte_ms = self._ticks_ms()
            read_count += received
            self._frame_read_calls += 1
            self._synchronize_magic()
            maximum_size = max(MAX_JSON_SIZE + 64, MAX_UPGRADE_LINE_SIZE + 64)
            if len(self._buffer) > maximum_size:
                self._buffer = bytearray()
                self._last_byte_ms = None
                self._write_frame("ERR", b"FRAME_TOO_LARGE")
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
            receive_finished_ms = self._ticks_ms()
            receive_elapsed_ms = self._elapsed_ms(
                receive_finished_ms, self._frame_started_ms
            )
            frame_read_calls = self._frame_read_calls
            self._consume(newline + 1)
            # 串口可能先被 ModemManager 等程序写入无换行的探测字节；扫描魔数，
            # 从同一行中的首个 PV1 帧重新同步，而不是连合法帧一起丢弃。
            frame_start = line.find(b"PV1:")
            if frame_start >= 0:
                line = line[frame_start:]
                try:
                    parse_started_ms = self._ticks_ms()
                    message_type, payload = self._parse_frame(line)
                    parse_elapsed_ms = self._elapsed_ms(
                        self._ticks_ms(), parse_started_ms
                    )
                except ValueError as error:
                    self._write_frame("ERR", str(error).encode("ascii"))
                    continue
                if message_type == "PING":
                    self._write_pong()
                elif message_type == "JSON":
                    try:
                        json_started_ms = self._ticks_ms()
                        latest = json.loads(payload.decode("utf-8"))
                        json_elapsed_ms = self._elapsed_ms(
                            self._ticks_ms(), json_started_ms
                        )
                        timing = (
                            "PROTOCOL_TIMING:TYPE=JSON:BYTES={}:READS={}:"
                            "RX={}MS:FRAME_PARSE={}MS:JSON={}MS"
                        ).format(
                            len(line),
                            frame_read_calls,
                            receive_elapsed_ms,
                            parse_elapsed_ms,
                            json_elapsed_ms,
                        )
                        self._write_frame("EVENT", timing.encode("ascii"))
                        self._write_frame("ACK", b"JSON")
                    except (ValueError, UnicodeError):
                        self._write_frame("ERR", b"BAD_JSON")
                elif message_type == "UPGRADE":
                    if self._upgrade_manager is None:
                        self._write_frame("ERR", b"UPGRADE_UNAVAILABLE")
                    else:
                        self._upgrade_manager.handle(payload)
                else:
                    self._write_frame("ERR", b"UNKNOWN_TYPE")
                continue
        return latest

    def _consume(self, count):
        """重建剩余缓冲区以兼容 RP2040 MicroPython。"""
        if count >= len(self._buffer):
            self._buffer = bytearray()
            self._last_byte_ms = None
            self._frame_started_ms = None
            self._frame_read_calls = 0
        else:
            self._buffer = bytearray(self._buffer[count:])

    def _write_pong(self):
        """返回设备能力、硬件型号、屏幕方案及固件版本。"""
        payload = json.dumps({
            "board_model": BOARD_MODEL,
            "screen_color_profile": SCREEN_COLOR_PROFILE,
            "firmware_version": FIRMWARE_VERSION,
            "device_name": DEVICE_NAME,
            "lcd_driver": LCD_DRIVER,
            "width": WIDTH,
            "height": HEIGHT,
            "pixel_format": PIXEL_FORMAT,
        }).encode("utf-8")
        self._write_frame("PONG", payload)

    def write_upgrade_response(self, data):
        """把升级状态封装为 PV1 响应帧。"""
        self._write_frame("STATUS", bytes(data).strip())

    @staticmethod
    def _crc16(data):
        """使用字节查表计算 CRC-16/CCITT-FALSE。"""
        crc = 0xFFFF
        for value in data:
            crc = ((crc << 8) & 0xFFFF) ^ CRC16_BYTE_TABLE[((crc >> 8) ^ value) & 0xFF]
        return crc

    @classmethod
    def _build_frame(cls, message_type, payload=b""):
        kind = message_type.encode("ascii") if isinstance(message_type, str) else bytes(message_type)
        payload = bytes(payload)
        checksum = cls._crc16(kind + b":" + payload)
        return b":".join((b"PV1", kind, str(len(payload)).encode(), ("%04X" % checksum).encode(), payload)) + b"\n"

    @classmethod
    def _parse_frame(cls, line):
        parts = bytes(line).split(b":", 4)
        if len(parts) != 5 or parts[0] != b"PV1":
            raise ValueError("BAD_FRAME_HEADER")
        try:
            length = int(parts[2])
            expected_crc = int(parts[3], 16)
        except ValueError:
            raise ValueError("BAD_FRAME_HEADER")
        remainder = parts[4]
        if length < 0 or length > MAX_JSON_SIZE or len(remainder) < length:
            raise ValueError("BAD_FRAME_LENGTH")
        payload = remainder[:length]
        if remainder[length:].strip(b" "):
            raise ValueError("BAD_FRAME_TRAILER")
        if cls._crc16(parts[1] + b":" + payload) != expected_crc:
            raise ValueError("BAD_FRAME_CRC")
        try:
            message_type = parts[1].decode("ascii")
        except UnicodeError:
            raise ValueError("BAD_FRAME_TYPE")
        return message_type, payload

    def _write_frame(self, message_type, payload=b""):
        self._write_raw(self._build_frame(message_type, payload))

    @staticmethod
    def _ticks_ms():
        ticks_ms = getattr(time, "ticks_ms", None)
        return ticks_ms() if ticks_ms else int(time.monotonic() * 1000)

    @staticmethod
    def _elapsed_ms(now, started):
        if started is None:
            return 0
        ticks_diff = getattr(time, "ticks_diff", None)
        return ticks_diff(now, started) if ticks_diff else now - started

    def _expire_partial_frame(self):
        """丢弃超过一秒没有新字节的半包，恢复协议同步。"""
        if not self._buffer or self._last_byte_ms is None:
            return
        now = self._ticks_ms()
        ticks_diff = getattr(time, "ticks_diff", None)
        idle_ms = ticks_diff(now, self._last_byte_ms) if ticks_diff else now - self._last_byte_ms
        if idle_ms >= 1000:
            self._buffer = bytearray()
            self._last_byte_ms = None
            self._frame_started_ms = None
            self._frame_read_calls = 0
            self._write_frame("ERR", b"FRAME_TIMEOUT")

    def _synchronize_magic(self):
        """丢弃魔数之前的串口探测垃圾，并保留可能的魔数前缀。"""
        start = self._buffer.find(b"PV1:")
        if start > 0:
            self._buffer = bytearray(self._buffer[start:])
            self._frame_started_ms = self._ticks_ms()
            self._frame_read_calls = 1
        elif start == 0 and self._frame_started_ms is None:
            self._frame_started_ms = self._ticks_ms()
        elif start < 0 and len(self._buffer) > 3:
            self._buffer = bytearray(self._buffer[-3:])
