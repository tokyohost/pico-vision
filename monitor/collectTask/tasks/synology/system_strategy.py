"""实现群晖 DSM 系统专用采集策略。"""

import os

from ..nas_strategy import LinuxNasCollectionStrategy
from .cpu_percent import CpuPercentSampler


SYNOLOGY_MARKER_FILES = (
    "/etc.defaults/VERSION",
    "/etc/synoinfo.conf",
)


def is_synology_system(system_name, marker_files=SYNOLOGY_MARKER_FILES):
    """根据 Linux 平台和 DSM 标志文件判断当前系统是否为群晖。"""
    return system_name == "Linux" and any(os.path.isfile(path) for path in marker_files)


class SynologyCollectionStrategy(LinuxNasCollectionStrategy):
    """处理群晖 DSM 的 CPU 占用率、频率和温度采集。"""

    priority = 300

    def supports(self, system_name):
        """判断目标系统是否为群晖 DSM。"""
        return is_synology_system(system_name)

    def create_cpu_percent_sampler(self, logger):
        """创建读取 /proc/stat 的群晖 CPU 占用率采样器。"""
        return CpuPercentSampler(logger)
