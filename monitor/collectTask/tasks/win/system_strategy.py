"""实现 Windows 系统采集策略。"""

from ..system_strategy import SystemCollectionStrategy
from .cpu_percent import CpuPercentSampler


class WindowsCollectionStrategy(SystemCollectionStrategy):
    """处理 Windows 系统的专用指标采集。"""

    priority = 200

    def supports(self, system_name):
        """判断目标系统是否为 Windows。"""
        return system_name == "Windows"

    def create_cpu_percent_sampler(self, logger):
        """创建基于 Windows 性能计数器的 CPU 占用率采样器。"""
        return CpuPercentSampler(logger)
