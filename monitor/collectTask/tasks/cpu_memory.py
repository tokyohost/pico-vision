"""CPU 和内存采集任务。"""

import importlib
import logging
import platform
import time

import psutil

from history import update_per_second

from ..system_tasks import CollectionTask


CPU_SAMPLE_WINDOW_SECONDS = 0.5
LOGGER = logging.getLogger("pico-monitor.collector")


def _cpu_sampler_class():
    """根据当前平台返回 CPU 占用率采样实现类。"""
    module_name = ".win.cpu_percent" if platform.system() == "Windows" else ".linux.cpu_percent"
    module = importlib.import_module(module_name, package=__package__)
    return module.CpuPercentSampler


class CpuMemoryTask(CollectionTask):
    """采集 CPU、内存、CPU 频率与温度并维护对应历史序列。"""

    name = "cpu_memory"
    zh_name = "CPU与内存采集"
    default_interval = 1.0
    order = 20

    def __init__(self, collector):
        """初始化 CPU 采集任务，并延迟创建当前平台采样器。"""
        super().__init__(collector)
        self._cpu_sampler = None

    def collect(self):
        """通过短阻塞窗口采样 CPU，并返回 CPU 和内存两个顶层指标。"""
        use_sensor_host_cpu = self._sensor_host_available("cpu")
        use_sensor_host_memory = self._sensor_host_available("memory")
        if use_sensor_host_cpu and use_sensor_host_memory:
            return {}
        cpu = None if use_sensor_host_cpu else round(self._cpu_percent(), 1)
        memory = None if use_sensor_host_memory else psutil.virtual_memory()
        now = time.monotonic()
        fragment = {}
        if cpu is not None:
            update_per_second(
                self.collector.histories["cpu"],
                round(cpu, 1),
                self.collector.history_states.setdefault("cpu", {}),
                now,
            )
            fragment["cpu"] = {
                "percent": cpu,
                "frequency_ghz": self.collector._cpu_frequency_ghz(),
                "temperature_c": self._cpu_temperature(),
                "history": list(self.collector.histories["cpu"]),
            }
        if memory is not None:
            update_per_second(
                self.collector.histories["memory"],
                round(memory.percent, 1),
                self.collector.history_states.setdefault("memory", {}),
                now,
            )
            fragment["memory"] = {
                "percent": round(memory.percent, 1),
                "used_bytes": memory.used,
                "total_bytes": memory.total,
                "history": list(self.collector.histories["memory"]),
            }
        if self._sensor_host_available("cpu"):
            fragment.pop("cpu", None)
        if self._sensor_host_available("memory"):
            fragment.pop("memory", None)
        return fragment

    def _sensor_host_available(self, metric_name):
        """判断 SensorHost 是否正在优先提供指定指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker(metric_name))

    def _cpu_temperature(self):
        """优先复用 SensorHost CPU 温度，缺失时再执行本地温度采集。"""
        if self._sensor_host_available("cpu_temperature"):
            cpu = getattr(self.collector, "_sensor_host_cpu_fragment", {}) or {}
            if cpu.get("temperature_c") is not None:
                return cpu.get("temperature_c")
        return self.collector._cpu_temperature()

    def _cpu_percent(self):
        """通过当前平台采样器读取每核心平均 CPU 占用率。"""
        if self._cpu_sampler is None:
            self._cpu_sampler = _cpu_sampler_class()(LOGGER)
        return self._cpu_sampler.sample(CPU_SAMPLE_WINDOW_SECONDS)
