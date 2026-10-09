"""macOS 磁盘容量与健康采集任务。"""

from ..disk_capacity_health import DiskCapacityHealthTask as BaseDiskCapacityHealthTask


class MacOsDiskCapacityHealthTask(BaseDiskCapacityHealthTask):
    """在 macOS 上复用统一的磁盘容量与健康快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

