"""CPU 和内存采集任务。"""

import time

import psutil

from history import update_per_second

from ..system_tasks import CollectionTask


class CpuMemoryTask(CollectionTask):
    """采集 CPU、内存、CPU 频率与温度并维护对应历史序列。"""

    name = "CPU与内存采集"
    default_interval = 1.0
    order = 20

    def collect(self):
        """返回 CPU 和内存两个顶层指标。"""
        cpu = round(psutil.cpu_percent(interval=None), 1)
        memory = psutil.virtual_memory()
        now = time.monotonic()
        for name, value in (("cpu", cpu), ("memory", memory.percent)):
            update_per_second(
                self.collector.histories[name],
                round(value, 1),
                self.collector.history_states.setdefault(name, {}),
                now,
            )
        return {
            "cpu": {
                "percent": cpu,
                "frequency_ghz": self.collector._cpu_frequency_ghz(),
                "temperature_c": self.collector._cpu_temperature(),
                "history": list(self.collector.histories["cpu"]),
            },
            "memory": {
                "percent": round(memory.percent, 1),
                "used_bytes": memory.used,
                "total_bytes": memory.total,
                "history": list(self.collector.histories["memory"]),
            },
        }