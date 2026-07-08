"""基础信息采集任务。"""

import datetime as dt
import platform
import socket
import time

import psutil

from ..system_tasks import CollectionTask


class BasicInformationTask(CollectionTask):
    """采集主机身份、系统平台、时间戳和运行时长。"""

    name = "基础信息采集"
    default_interval = 1.0
    order = 10

    def collect(self):
        """返回不依赖其他指标的基础快照字段。"""
        return {
            "version": 1,
            "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname(),
            "platform": platform.system(),
            "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
        }