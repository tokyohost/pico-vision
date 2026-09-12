"""实现通用 USB CDC 传输策略。"""

try:
    import uselect as select
except ImportError:
    import select

from net.base import TransportStrategy


class UsbCdcTransport(TransportStrategy):
    """把 MicroPython USB CDC 数据接口适配为统一传输策略。"""

    name = "usb"

    def __init__(self, stream):
        """保存 CDC 数据流并创建非阻塞可读性轮询器。"""
        self._stream = stream
        self._poller = None
        if not callable(getattr(stream, "any", None)):
            self._poller = select.poll()
            poll_target = getattr(stream, "poll_target", None)
            poll_target = poll_target() if callable(poll_target) else stream
            self._poller.register(poll_target, select.POLLIN)

    def update(self):
        """USB CDC 由固件中断驱动，本轮无需额外推进。"""
        return None

    def is_connected(self):
        """返回主机是否已打开 CDC 数据端口。"""
        checker = getattr(self._stream, "is_open", None)
        return bool(checker()) if callable(checker) else True

    def available(self):
        """返回 CDC 是否存在可立即读取的数据。"""
        if not self.is_connected():
            return 0
        counter = getattr(self._stream, "any", None)
        if callable(counter):
            return counter()
        return 1 if self._poller.poll(0) else 0

    def supports_binary_frames(self):
        """返回底层 CDC 是否绕过 REPL 并支持原始二进制。"""
        checker = getattr(self._stream, "supports_binary_frames", None)
        return bool(checker()) if callable(checker) else True

    def uses_complete_frame_queue(self):
        """返回 CDC 底层是否直接提供 C 层已组装完整帧。"""
        checker = getattr(self._stream, "uses_complete_frame_queue", None)
        return bool(checker()) if callable(checker) else False

    def read_frame(self):
        """从 C 层 CDC 帧队列取出一个完整帧。"""
        reader = getattr(self._stream, "read_frame", None)
        return reader() if callable(reader) else None

    def read_receive_error(self):
        """取出 C 层 CDC 接收任务上报的异步错误。"""
        reader = getattr(self._stream, "read_receive_error", None)
        return reader() if callable(reader) else None

    def readinto(self, buffer):
        """从 CDC 接口读取数据到目标缓冲区。"""
        return self._stream.readinto(buffer)

    def write(self, data):
        """向 CDC 接口写入数据。"""
        return self._stream.write(data)

    def flush(self):
        """刷新 CDC 发送缓冲区。"""
        flush = getattr(self._stream, "flush", None)
        return flush() if callable(flush) else None

    def close(self):
        """关闭 CDC 数据流。"""
        close = getattr(self._stream, "close", None)
        return close() if callable(close) else None
