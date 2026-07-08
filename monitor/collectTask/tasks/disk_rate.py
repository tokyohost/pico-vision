"""磁盘实时读写速率采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_RATE_FIELDS, disk_snapshot_disks, publish_disk_snapshot


class DiskRateTask(CollectionTask):
    """采集磁盘实时读写速率和历史序列，高频刷新轻量 IO 指标。"""

    name = "磁盘读写速率采集"
    default_interval = 1.0
    order = 32

    def collect(self):
        """返回合并后的磁盘实时读写速率指标。"""
        disks = disk_snapshot_disks(self.collector)
        if not disks:
            self.collector._refresh_disk_hardware_state()
            disks = self.collector._disk_details()
        disks = self.collector._disk_rates(disks)
        return publish_disk_snapshot(
            self.collector,
            disks=disks,
            physical_disks=self.collector._physical_disk_statistics(disks),
            disk_fields=DISK_RATE_FIELDS,
            physical_fields=DISK_RATE_FIELDS,
        )
