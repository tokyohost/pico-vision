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

"""定义系统监控采集模块共享的常量和日志对象。"""

import logging


LOGGER = logging.getLogger("pico-monitor")

DISK_TEMPERATURE_CACHE_SECONDS = 30
DISK_HEALTH_CACHE_SECONDS = 30 * 60
SENSOR_HOST_PRIORITY_TTL_SECONDS = 3.0

DISK_HEALTH_UNKNOWN = 0
DISK_HEALTH_HEALTHY = 1
DISK_HEALTH_NOTICE = 2
DISK_HEALTH_WARNING = 3
DISK_HEALTH_CRITICAL = 4
DISK_HEALTH_FAILED = 5
