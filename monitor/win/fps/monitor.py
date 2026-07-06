"""协调主采集器与可选回退采集器的 FPS 监控模块。"""

import logging
import platform
from collections import deque

from history import update_per_second

from .adlx import AdlxBackend
from .presentmon import PresentMonBackend

LOGGER = logging.getLogger("pico-monitor")


class FpsMonitor:
    """优先使用 PresentMon/ETW，并在无采样时回退到 AMD ADLX。"""

    def __init__(self, history_length=24, backend_factories=None):
        """初始化历史队列，并按优先级创建可用采集器。"""
        self.history = deque([0] * int(history_length), maxlen=int(history_length))
        self.history_state = {}
        self.backends = []
        self._last_log_state = None
        if platform.system() == "Windows":
            factories = backend_factories or (PresentMonBackend, AdlxBackend)
            for factory in factories:
                backend_name = getattr(factory, "__name__", factory.__class__.__name__)
                try:
                    backend = factory()
                    self.backends.append(backend)
                    LOGGER.info("[FPS] 采集器初始化成功：%s", backend.__class__.__name__)
                except (AttributeError, OSError) as error:
                    LOGGER.warning("[FPS] 采集器初始化失败：%s，原因=%s", backend_name, error)
        else:
            LOGGER.info("[FPS] 当前系统不是 Windows，FPS 采集未启用")

    def start(self):
        """启动所有成功初始化的 FPS 采集器。"""
        if not self.backends:
            LOGGER.warning("[FPS] 没有可用的 FPS 采集器，后续 value 将返回 null")
        for backend in self.backends:
            LOGGER.info("[FPS] 正在启动采集器：%s", backend.__class__.__name__)
            backend.start()

    def close(self):
        """关闭所有 FPS 采集器。"""
        for backend in self.backends:
            backend.close()

    def snapshot(self, now=None):
        """按优先级获取 FPS，并在状态变化时记录诊断日志。"""
        sample = None
        empty_backends = []
        for backend in self.backends:
            backend_name = backend.__class__.__name__
            try:
                sample = backend.snapshot()
            except (AttributeError, OSError, ValueError) as error:
                LOGGER.warning("[FPS] 采集器读取异常：%s，原因=%s", backend_name, error)
                sample = None
            if sample is not None:
                break
            reason = getattr(backend, "diagnostic_reason", "当前没有有效采样")
            empty_backends.append("{}：{}".format(backend_name, reason))
        if sample is not None:
            value = round(max(0.0, float(sample["value"])), 1)
            sample = dict(sample)
            sample["value"] = value
            log_state = (sample.get("source"), sample.get("process_id"), value)
            if log_state != self._last_log_state:
                LOGGER.info(
                    "[FPS] 获取成功：value=%.1f，source=%s，pid=%s，process=%s",
                    value,
                    sample.get("source", ""),
                    sample.get("process_id"),
                    sample.get("process_name", ""),
                )
                self._last_log_state = log_state
        else:
            log_state = ("unavailable", tuple(empty_backends))
            if log_state != self._last_log_state:
                LOGGER.warning(
                    "[FPS] 获取结果为 null：%s",
                    "；".join(empty_backends) if empty_backends else "没有成功初始化的采集器",
                )
                self._last_log_state = log_state
        update_per_second(
            self.history,
            sample["value"] if sample is not None else 0.0,
            self.history_state,
            now,
        )
        return {
            "value": sample["value"] if sample else None,
            "history": list(self.history),
            "source": sample["source"] if sample else "unavailable",
            "process_id": sample.get("process_id") if sample else None,
            "process_name": sample.get("process_name", "") if sample else "",
        }
