"""协调非阻塞 JSON 接收与最新快照缓存。"""


class SnapshotCache:
    """在单核事件循环中保存最新系统快照及版本号。"""

    def __init__(self):
        """创建空快照缓存。"""
        self.snapshot = None
        self.version = 0

    def update(self, snapshot):
        """替换最新快照并递增版本号。"""
        self.snapshot = snapshot
        self.version += 1

    def latest(self):
        """返回最新快照和版本号。"""
        return self.snapshot, self.version


class DataReceiver:
    """在主循环中轮询协议，不创建 RP2040 第二核心线程。"""

    def __init__(self, protocol, cache, led):
        """保存协议、缓存和状态灯控制器。"""
        self._protocol = protocol
        self._cache = cache
        self._led = led

    def update(self):
        """执行一次非阻塞接收并缓存有效 JSON。"""
        snapshot = self._protocol.poll()
        if snapshot is None:
            return False
        self._cache.update(snapshot)
        self._led.notify_data()
        return True

    def is_busy(self):
        """返回协议层是否仍在接收一条未完成的数据包。"""
        return self._protocol.is_busy()
