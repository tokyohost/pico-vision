"""处理 Pico USB 串口握手和 JSON 数据包接收。"""

import struct
import sys
import time

try:
    import ujson as json
except ImportError:
    import json

try:
    import uselect as select
except ImportError:
    try:
        import select
    except ImportError:
        select = None

from config import (
    DEVICE_NAME,
    HEIGHT,
    JSON_MAGIC,
    LCD_DRIVER,
    MAX_JSON_SIZE,
    PING_TEXT,
    PIXEL_FORMAT,
    WIDTH,
)


class JsonProtocol:
    """处理 USB 串口握手和带长度前缀的 JSON 数据包。"""

    def __init__(self):
        """获取标准输入输出的二进制串口流。"""
        self.input = getattr(sys.stdin, "buffer", sys.stdin)
        self.output = getattr(sys.stdout, "buffer", sys.stdout)

    def write(self, data):
        """通过 USB 串口向系统端发送二进制响应。"""
        self.output.write(data)
        try:
            self.output.flush()
        except Exception:
            pass

    def read_exact(self, length):
        """从 USB 串口阻塞读取指定数量的字节。"""
        result = bytearray(length)
        view = memoryview(result)
        position = 0
        while position < length:
            chunk = self.input.read(length - position)
            if chunk:
                size = len(chunk)
                view[position:position + size] = chunk
                position += size
            else:
                time.sleep_ms(1)
        return result

    def read_line(self, first_byte, maximum=128):
        """从首字节开始读取一个长度受限的文本命令。"""
        result = bytearray(first_byte)
        while len(result) < maximum:
            byte = self.input.read(1)
            if byte:
                result.extend(byte)
                if byte == b"\n":
                    break
            else:
                time.sleep_ms(1)
        return bytes(result)

    def discard(self, length):
        """丢弃异常数据包的剩余字节，以恢复下一包协议同步。"""
        remaining = length
        while remaining > 0:
            size = min(remaining, 512)
            self.read_exact(size)
            remaining -= size

    def receive(self):
        """读取一个命令，返回新系统快照或空值。"""
        first = self.input.read(1)
        if not first:
            return None
        if first == b"P":
            line = self.read_line(first).strip()
            if line == PING_TEXT:
                response = "PONG:{}:{}:{}x{}:{}:JSON\n".format(
                    DEVICE_NAME,
                    LCD_DRIVER,
                    WIDTH,
                    HEIGHT,
                    PIXEL_FORMAT,
                )
                self.write(response.encode())
            return None
        if first != b"J":
            return None
        magic = first + self.read_exact(3)
        if magic != JSON_MAGIC:
            return None
        payload_size = struct.unpack(">I", self.read_exact(4))[0]
        if payload_size <= 0 or payload_size > MAX_JSON_SIZE:
            self.write(b"ERR:BAD_JSON_SIZE\n")
            if 0 < payload_size < 1024 * 1024:
                self.discard(payload_size)
            return None
        payload = self.read_exact(payload_size)
        try:
            return json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeError):
            self.write(b"ERR:BAD_JSON\n")
            return None


def create_poller(stream):
    """创建 USB 输入轮询器；不支持轮询时返回空值。"""
    if select is None or not hasattr(select, "poll"):
        return None
    poller = select.poll()
    poller.register(stream, select.POLLIN)
    return poller
