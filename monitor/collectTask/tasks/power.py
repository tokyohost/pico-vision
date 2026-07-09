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
        if self._sensor_host_available():
            return {}
        power = self.collector.power_monitor.snapshot()
        if self._sensor_host_available():
            return {}
        if power["watts"] is not None:
            update_per_second(
                self.collector.power_history,
                power["watts"],
                self.collector.history_states.setdefault("power", {}),
                time.monotonic(),
            )
        power["history"] = list(self.collector.power_history)
        return {"power": power}

    def _sensor_host_available(self):
        """判断 SensorHost 是否正在优先提供功耗指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker("power"))
