"""实现通用 Linux 系统采集策略。"""

from ..system_strategy import SystemCollectionStrategy
from .cpu_percent import CpuPercentSampler


class LinuxCollectionStrategy(SystemCollectionStrategy):
    """处理非群晖 Linux 系统的通用指标采集。"""

    priority = 100

    def supports(self, system_name):
        """判断目标系统是否为 Linux。"""
        return system_name == "Linux"

    def create_cpu_percent_sampler(self, logger):
        """创建基于 psutil 的 Linux CPU 占用率采样器。"""
        return CpuPercentSampler(logger)
