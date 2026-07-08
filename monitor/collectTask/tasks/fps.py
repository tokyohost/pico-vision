"""FPS 采集任务。"""

import time

from constants import HISTORY_LENGTH

from ..system_tasks import CollectionTask


class FpsTask(CollectionTask):
    """读取前台应用 FPS 后台采样结果。"""

    name = "fps"
    zh_name = "FPS采集"
    default_interval = 1.0
    order = 70

    def collect(self):
        """返回 FPS 指标或结构完整的不可用结果。"""
        if self.collector.fps_monitor is None:
            return {
                "fps": {
                    "value": None,
                    "history": [0] * HISTORY_LENGTH,
                    "source": "unavailable",
                    "process_id": None,
                    "process_name": "",
                }
            }
        return {"fps": self.collector.fps_monitor.snapshot(time.monotonic())}
