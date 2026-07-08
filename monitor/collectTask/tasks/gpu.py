"""GPU 采集任务。"""

import time

from history import update_per_second

from ..system_tasks import CollectionTask


class GpuTask(CollectionTask):
    """读取 GPU 后台采样结果并维护 GPU 使用率历史。"""

    name = "GPU采集"
    default_interval = 1.0
    order = 60

    def collect(self):
        """返回最近 GPU 指标；不可用时发布空值。"""
        gpu, version = self.collector.gpu_monitor.snapshot()
        if gpu is None:
            return {"gpu": None}
        gpu = dict(gpu)
        percent = gpu.get("percent")
        if percent is not None and version != self.collector.last_gpu_version:
            update_per_second(
                self.collector.gpu_history,
                percent,
                self.collector.history_states.setdefault("gpu", {}),
                time.monotonic(),
            )
        self.collector.last_gpu_version = version
        gpu["history"] = list(self.collector.gpu_history)
        return {"gpu": gpu}