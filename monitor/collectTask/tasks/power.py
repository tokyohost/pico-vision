"""功耗采集任务。"""

import time

from history import update_per_second

from ..system_tasks import CollectionTask


class PowerTask(CollectionTask):
    """采集系统功耗并维护可用功耗的历史序列。"""

    name = "power"
    zh_name = "功耗采集"
    default_interval = 1.0
    order = 50

    def collect(self):
        """返回电源指标和最近功耗历史。"""
        power = self.collector.power_monitor.snapshot()
        if power["watts"] is not None:
            update_per_second(
                self.collector.power_history,
                power["watts"],
                self.collector.history_states.setdefault("power", {}),
                time.monotonic(),
            )
        power["history"] = list(self.collector.power_history)
        return {"power": power}
