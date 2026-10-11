"""macOS CPU 与内存采集任务。"""

from ..cpu_memory import CpuMemoryTask as BaseCpuMemoryTask


class MacOsCpuMemoryTask(BaseCpuMemoryTask):
    """在 macOS 上复用统一的CPU 与内存快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

    def collect(self):
        """补充频率和温度来源，使实时值与标称降级值可区分。"""
        fragment = super().collect()
        telemetry = self.collector.mac_telemetry
        sample, _ = telemetry.snapshot()
        frequency, source = telemetry.cpu_frequency()
        fragment["cpu"].update(frequency_ghz=frequency, frequency_source=source,
                               temperature_source=sample["temperature_source"],
                               temperature_reason="当前后端没有可读取的 CPU 温度传感器" if sample["cpu_temperature_c"] is None else "",
                               frequency_reason="当前后端没有可读取的 CPU 频率" if frequency is None else "")
        return fragment
