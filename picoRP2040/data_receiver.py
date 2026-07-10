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



"""协调非阻塞 JSON 接收与最新快照缓存。"""


from config import (
    TIME_CALIBRATION_SNAPSHOTS,
    TIME_CALIBRATION_TOLERANCE_SECONDS,
)
from timeIncrease import TimeIncrease


def _merge_snapshot(previous, incoming):
    """递归合并快照字段，未出现在本次数据中的字段沿用旧值。"""
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return incoming
    merged = dict(previous)
    for key, value in incoming.items():
        old_value = merged.get(key)
        if isinstance(old_value, dict) and isinstance(value, dict):
            merged[key] = _merge_snapshot(old_value, value)
        else:
            merged[key] = value
    return merged



class SnapshotCache:
    """在单核事件循环中保存最新系统快照及版本号。"""

    def __init__(self):
        """创建空快照缓存。"""
        self.snapshot = None
        self.version = 0
        self._time_increase = TimeIncrease(
            TIME_CALIBRATION_SNAPSHOTS,
            TIME_CALIBRATION_TOLERANCE_SECONDS,
        )

    def update(self, snapshot):
        """合并最新快照并递增版本号。"""
        self.snapshot = self._time_increase.receive(
            _merge_snapshot(self.snapshot, snapshot)
        )
        self.version += 1

    def latest(self):
        """返回最新快照和版本号。"""
        return self._time_increase.increase(self.snapshot), self.version

    def clear(self):
        """清除失效快照并递增版本号。"""
        self.snapshot = None
        self._time_increase.reset()
        self.version += 1


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

    def replace_protocol(self, protocol):
        """在 USB CDC 重新注册后切换到新的协议实例。"""
        self._protocol = protocol
