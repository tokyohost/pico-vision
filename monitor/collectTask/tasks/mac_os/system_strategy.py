"""macOS 系统采集策略。"""

from ..system_strategy import SystemCollectionStrategy
from .cpu_percent import CpuPercentSampler


class MacOsCollectionStrategy(SystemCollectionStrategy):
    """为 Intel 与 Apple Silicon Mac 选择对应的 CPU 采集实现。"""

    def supports(self, system_name):
        """判断系统标识是否为 macOS 内核名称 Darwin。"""
        return system_name == "Darwin"

    def create_cpu_percent_sampler(self, logger):
        """创建基于 psutil 的 Darwin CPU 占用率采样器。"""
        return CpuPercentSampler(logger)

    def cpu_frequency_ghz(self, collector):
        """读取共享 macOS 遥测频率，避免使用 Linux 或 Windows 频率实现。"""
        return collector.mac_telemetry.cpu_frequency()[0]

    def cpu_temperature(self, collector):
        """读取共享原生采样中的 CPU SMC 温度。"""
        return collector.mac_telemetry.snapshot()[0]["cpu_temperature_c"]
