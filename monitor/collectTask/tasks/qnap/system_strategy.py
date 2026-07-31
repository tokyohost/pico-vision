"""实现威联通 QTS 与 QuTS hero 系统专用采集策略。"""

import os

from ..nas_cpu_percent import ProcStatCpuPercentSampler
from ..nas_strategy import LinuxNasCollectionStrategy


QNAP_MARKER_FILES = (
    "/etc/config/uLinux.conf",
    "/etc/default_config/uLinux.conf",
)


def is_qnap_system(system_name, marker_files=QNAP_MARKER_FILES):
    """根据 Linux 平台和 QNAP 配置文件判断当前系统是否为威联通。"""
    return system_name == "Linux" and any(os.path.isfile(path) for path in marker_files)


class QnapCollectionStrategy(LinuxNasCollectionStrategy):
    """处理威联通 QTS 与 QuTS hero 的专用指标采集。"""

    priority = 300

    def supports(self, system_name):
        """判断目标系统是否为威联通 QTS 或 QuTS hero。"""
        return is_qnap_system(system_name)

    def create_cpu_percent_sampler(self, logger):
        """创建读取 /proc/stat 的威联通 CPU 占用率采样器。"""
        return ProcStatCpuPercentSampler(logger)
