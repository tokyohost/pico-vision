#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

"""系统监控采集器兼容导出模块。"""

import platform
import subprocess
import time

import psutil

from monitor_core.collectors.models import (
    DISK_HEALTH_CRITICAL,
    DISK_HEALTH_FAILED,
    DISK_HEALTH_HEALTHY,
    DISK_HEALTH_NOTICE,
    DISK_HEALTH_UNKNOWN,
    DISK_HEALTH_WARNING,
)
from monitor_core.collectors.gpu import GpuMonitor
from monitor_core.collectors.network import PingMonitor
from monitor_core.collectors.power import PowerMonitor
from monitor_core.collectors.system_collector import SystemInformationCollector

__all__ = [
    "DISK_HEALTH_CRITICAL",
    "DISK_HEALTH_FAILED",
    "DISK_HEALTH_HEALTHY",
    "DISK_HEALTH_NOTICE",
    "DISK_HEALTH_UNKNOWN",
    "DISK_HEALTH_WARNING",
    "GpuMonitor",
    "PingMonitor",
    "PowerMonitor",
    "SystemInformationCollector",
    "platform",
    "psutil",
    "subprocess",
    "time",
]
