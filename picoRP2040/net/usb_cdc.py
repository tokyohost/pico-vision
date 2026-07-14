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
        return 1 if self._poller.poll(0) else 0

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
