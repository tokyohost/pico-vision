"""为 ESP32-S3 内置 USB 控制台提供 PV1 二进制双工数据流。"""

import sys
import time

try:
    import uselect as select
except ImportError:
    import select

from config import USB_SESSION_TIMEOUT_MS


def _ticks_ms():
    """返回 MicroPython 单调毫秒时钟，并支持本地静态检查环境。"""
    getter = getattr(time, "ticks_ms", None)
    if callable(getter):
        return getter()
    return int(time.monotonic() * 1000)


def _ticks_diff(newer, older):
    """计算支持 MicroPython 时钟环绕的毫秒差值。"""
    calculator = getattr(time, "ticks_diff", None)
    if callable(calculator):
        return calculator(newer, older)
    return newer - older


class Esp32S3UsbStream:
    """把 ESP32-S3 内置 USB 控制台封装为非阻塞二进制数据流。"""

    def __init__(
        self,
        input_stream=None,
        output_stream=None,
        session_timeout_ms=USB_SESSION_TIMEOUT_MS,
    ):
        """保存控制台输入输出，并初始化会话活动检测状态。"""
        self._input = sys.stdin if input_stream is None else input_stream
        self._reader = getattr(self._input, "buffer", self._input)
        self._output = sys.stdout if output_stream is None else output_stream
        self._writer = getattr(self._output, "buffer", self._output)
        self._session_timeout_ms = max(1, int(session_timeout_ms))
        self._connected = False
        self._last_activity_ms = None
        self._poller = select.poll()
        self._poller.register(self._input, select.POLLIN)

    def poll_target(self):
        """返回用于检测控制台可读事件的文本流对象。"""
        return self._input

    def _mark_activity(self):
        """记录 USB 会话活动并更新连接状态。"""
        self._connected = True
        self._last_activity_ms = _ticks_ms()

    def is_open(self):
        """根据输入活动和会话超时返回当前连接状态。"""
        if self._poller.poll(0):
            self._mark_activity()
        elif self._connected and self._last_activity_ms is not None:
            elapsed = _ticks_diff(_ticks_ms(), self._last_activity_ms)
            if elapsed >= self._session_timeout_ms:
                self._connected = False
                self._last_activity_ms = None
        return self._connected

    def readinto(self, buffer):
        """非阻塞读取控制台已有字节并写入目标缓冲区。"""
        if not buffer:
            return 0
        nonblocking_reader = getattr(self._reader, "readinto_nonblocking", None)
        if callable(nonblocking_reader):
            count = int(nonblocking_reader(buffer) or 0)
            if count > 0:
                self._mark_activity()
            return count

        target = memoryview(buffer)[:1]
        reader = getattr(self._reader, "readinto", None)
        if callable(reader):
            count = reader(target)
        else:
            data = self._reader.read(1)
            if isinstance(data, str):
                data = data.encode("utf-8")
            count = len(data or b"")
            if count:
                target[:count] = data
        count = int(count or 0)
        if count > 0:
            self._mark_activity()
        return count

    def write(self, data):
        """通过 ESP32-S3 内置 USB 控制台发送二进制数据。"""
        try:
            written = self._writer.write(data)
        except TypeError:
            self._writer.write(bytes(data).decode("utf-8"))
            written = len(data)
        if written is None:
            written = len(data)
        written = int(written)
        if written > 0:
            self._mark_activity()
        return written

    def flush(self):
        """保持控制台非阻塞，写入操作已由固件直接提交。"""
        return None

    def close(self):
        """释放 PV1 会话状态但保留系统内置控制台。"""
        self._connected = False
        self._last_activity_ms = None


def create_usb_stream(
    input_stream=None,
    output_stream=None,
    session_timeout_ms=USB_SESSION_TIMEOUT_MS,
):
    """创建 ESP32-S3 内置 USB 控制台数据流。"""
    return Esp32S3UsbStream(
        input_stream=input_stream,
        output_stream=output_stream,
        session_timeout_ms=session_timeout_ms,
    )
