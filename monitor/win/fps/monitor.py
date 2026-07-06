"""Public FPS monitor coordinating primary and optional backends."""

import platform
from collections import deque

from history import update_per_second

from .adlx import AdlxBackend
from .presentmon import PresentMonBackend


class FpsMonitor:
    """Prefer PresentMon/ETW and use AMD ADLX only when the primary has no sample."""

    def __init__(self, history_length=24, backend_factories=None):
        self.history = deque([0] * int(history_length), maxlen=int(history_length))
        self.history_state = {}
        self.backends = []
        if platform.system() == "Windows":
            factories = backend_factories or (PresentMonBackend, AdlxBackend)
            for factory in factories:
                try:
                    self.backends.append(factory())
                except (AttributeError, OSError):
                    continue

    def start(self):
        for backend in self.backends:
            backend.start()

    def close(self):
        for backend in self.backends:
            backend.close()

    def snapshot(self, now=None):
        sample = None
        for backend in self.backends:
            try:
                sample = backend.snapshot()
            except (AttributeError, OSError, ValueError):
                sample = None
            if sample is not None:
                break
        if sample is not None:
            value = round(max(0.0, float(sample["value"])), 1)
            sample = dict(sample)
            sample["value"] = value
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
