"""macOS 磁盘温度采集任务。"""

from ..disk_temperature import DiskTemperatureTask as BaseDiskTemperatureTask


class MacOsDiskTemperatureTask(BaseDiskTemperatureTask):
    """在 macOS 上复用统一的磁盘温度快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

