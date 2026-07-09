"""维护 JSON ACK 请求耗时记录的自动过期缓存。"""

import threading
import time
from collections import OrderedDict


DEFAULT_JSON_ACK_PENDING_LIMIT = 128
DEFAULT_JSON_ACK_TIMING_TTL_SECONDS = 6000.0


class ExpiringJsonAckTimingCache:
    """保存 JSON ACK 计时记录，并自动淘汰超过存活时间的旧数据。"""

    def __init__(
            self,
            ttl_seconds=DEFAULT_JSON_ACK_TIMING_TTL_SECONDS,
            limit=DEFAULT_JSON_ACK_PENDING_LIMIT,
    ):
        """初始化过期秒数、最大容量和线程锁。"""
        self.ttl_seconds = max(0.1, float(ttl_seconds))
        self.limit = max(1, int(limit))
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def put(self, request_id, timing):
        """写入或覆盖一个请求计时记录，并清理过期或超量数据。"""
        key = str(request_id)
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            self._items[key] = dict(timing)
            self._items.move_to_end(key)
            self._purge_overflow_locked()

    def update(self, request_id, timing):
        """补充已有请求计时记录；若 ACK 已先到达则静默忽略。"""
        key = str(request_id)
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            item = self._items.get(key)
            if item is None:
                return False
            item.update(timing)
            self._items.move_to_end(key)
            return True

    def pop(self, request_id):
        """取出指定请求的计时记录，过期或不存在时返回 None。"""
        key = str(request_id)
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            return self._items.pop(key, None)

    def pop_oldest(self):
        """取出最早的未过期计时记录，用于兼容无 request_id 的旧 ACK。"""
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            if not self._items:
                return None, None
            key, timing = self._items.popitem(last=False)
            return key, timing

    def __len__(self):
        """返回当前未过期记录数量。"""
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            return len(self._items)

    def snapshot(self):
        """返回当前未过期计时记录的调试快照。"""
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now)
            return [
                {
                    "request_id": key,
                    "age_ms": round((now - timing.get("created_at", now)) * 1000, 1),
                    "send_started": timing.get("send_started") is not None,
                    "send_finished": timing.get("send_finished") is not None,
                    "build_elapsed_ms": round(timing.get("build_elapsed_ms", 0.0), 1),
                    "send_elapsed_ms": round(timing.get("send_elapsed_ms", 0.0), 1),
                }
                for key, timing in self._items.items()
            ]

    def _purge_expired_locked(self, now):
        """删除所有已经超过存活时间的计时记录。"""
        deadline = now - self.ttl_seconds
        while self._items:
            _, timing = next(iter(self._items.items()))
            created_at = timing.get("created_at", timing.get("build_started", now))
            if created_at > deadline:
                break
            self._items.popitem(last=False)

    def _purge_overflow_locked(self):
        """容量超过上限时删除最旧的计时记录。"""
        while len(self._items) > self.limit:
            self._items.popitem(last=False)
