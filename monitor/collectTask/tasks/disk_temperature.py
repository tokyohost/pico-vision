"""磁盘温度采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_TEMPERATURE_FIELDS, publish_disk_snapshot


class DiskTemperatureTask(CollectionTask):
    """采集磁盘温度，并合并到已有磁盘容量和读写速率快照。"""

    name = "磁盘温度采集"
    default_interval = 5.0
    order = 31

    def collect(self):
        """返回合并后的磁盘温度指标。"""
        self.collector._refresh_disk_hardware_state()
        disks = self.collector._disk_details()
        return publish_disk_snapshot(
            self.collector,
            disks=disks,
            physical_disks=self.collector._physical_disk_statistics(disks),
            disk_fields=DISK_TEMPERATURE_FIELDS,
            physical_fields=DISK_TEMPERATURE_FIELDS,
        )
