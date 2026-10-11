"""macOS 磁盘读写速率采集任务。"""

from ..disk_rate import DiskRateTask as BaseDiskRateTask


class MacOsDiskRateTask(BaseDiskRateTask):
    """在 macOS 上复用统一的磁盘读写速率快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

