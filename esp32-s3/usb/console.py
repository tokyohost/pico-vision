"""封装 ESP32-S3 内置控制台的非阻塞双工数据流。"""

import sys
import time

try:
    import uselect as select
except ImportError:
    import select


def _ticks_ms():
    """返回 MicroPython 单调毫秒时钟，并兼容桌面测试环境。"""
    getter = getattr(time, "ticks_ms", None)
    return getter() if callable(getter) else int(time.monotonic() * 1000)


def _ticks_diff(newer, older):
    """计算支持 MicroPython 时钟回绕的毫秒差值。"""
    calculator = getattr(time, "ticks_diff", None)
    return calculator(newer, older) if callable(calculator) else newer - older


class Esp32S3ConsoleStream:
    """把内置 USB CDC 或 UART REPL 控制台适配为非阻塞数据流。"""

    def __init__(self, input_stream=None, output_stream=None, session_timeout_ms=5000):
        """保存控制台流并初始化基于输入活动的会话状态。"""
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
        """返回用于检查控制台可读事件的流对象。"""
        return self._input

    def _mark_activity(self):
        """记录最近一次控制台活动并锁定当前会话。"""
        self._connected = True
        self._last_activity_ms = _ticks_ms()

    def is_open(self):
        """根据输入活动与空闲超时判断控制台会话是否可用。"""
        if self._poller.poll(0):
            self._mark_activity()
        elif self._connected and self._last_activity_ms is not None:
            if _ticks_diff(_ticks_ms(), self._last_activity_ms) >= self._session_timeout_ms:
                self._connected = False
                self._last_activity_ms = None
        return self._connected

    def readinto(self, buffer):
        """立即读取当前已到达的数据，标准固件回退为单字节读取。"""
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
        """通过内置控制台发送二进制数据并记录会话活动。"""
        try:
            written = self._writer.write(data)
        except TypeError:
            self._writer.write(bytes(data).decode("utf-8"))
            written = len(data)
        written = len(data) if written is None else int(written)
        if written > 0:
            self._mark_activity()
        return written

    def flush(self):
        """保持控制台写入非阻塞，不额外等待底层发送完成。"""
        return None

    def close(self):
        """释放当前控制台会话状态但不关闭系统标准流。"""
        self._connected = False
        self._last_activity_ms = None

