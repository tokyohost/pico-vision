"""实现 TrueNAS SCALE 与 CORE 系统专用采集策略。"""

import os
import platform

from ..linux.cpu_percent import CpuPercentSampler as PsutilCpuPercentSampler
from ..nas_cpu_percent import ProcStatCpuPercentSampler
from ..nas_strategy import LinuxNasCollectionStrategy


TRUENAS_MARKER_FILES = (
    "/etc/truenas-release",
    "/data/freenas-v1.db",
)
TRUENAS_VERSION_FILES = (
    "/etc/version",
)


def _contains_truenas_identity(path):
    """判断版本文件是否包含 TrueNAS 或历史 FreeNAS 身份标志。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as version_file:
            content = version_file.read(256).lower()
    except OSError:
        return False
    return "truenas" in content or "freenas" in content


def is_truenas_system(
    system_name,
    marker_files=TRUENAS_MARKER_FILES,
    version_files=TRUENAS_VERSION_FILES,
):
    """根据平台、标志文件和版本内容判断当前系统是否为 TrueNAS。"""
    if system_name not in ("Linux", "FreeBSD"):
        return False
    if any(os.path.isfile(path) for path in marker_files):
        return True
    return any(_contains_truenas_identity(path) for path in version_files if os.path.isfile(path))


class TrueNasCollectionStrategy(LinuxNasCollectionStrategy):
    """处理 TrueNAS SCALE 与 CORE 的专用指标采集。"""

    priority = 300

    def supports(self, system_name):
        """判断目标系统是否为 TrueNAS SCALE 或 CORE。"""
        return is_truenas_system(system_name)

    def create_cpu_percent_sampler(self, logger):
        """根据 TrueNAS 内核选择 proc 或 psutil CPU 占用率采样器。"""
        if platform.system() == "Linux":
            return ProcStatCpuPercentSampler(logger)
        return PsutilCpuPercentSampler(logger)
