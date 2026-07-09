"""磁盘实时读写速率采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_RATE_FIELDS, collect_shared_disk_details, disk_snapshot_disks, publish_disk_snapshot


class DiskRateTask(CollectionTask):
    """采集磁盘实时读写速率和历史序列，高频刷新轻量 IO 指标。"""

    name = "disk_rate"
    zh_name = "磁盘读写速率采集"
    default_interval = 1.0
    order = 32

    def collect(self):
        """返回合并后的磁盘实时读写速率指标。"""
        if self._sensor_host_available():
            return {}
        disks = disk_snapshot_disks(self.collector)
        if not disks:
            disks = collect_shared_disk_details(self.collector, refresh_hardware=True)
        disks = self.collector._disk_rates(disks)
        if self._sensor_host_available():
            return {}
        return publish_disk_snapshot(
            self.collector,
            disks=disks,
            physical_disks=self.collector._physical_disk_statistics(disks),
            disk_fields=DISK_RATE_FIELDS,
            physical_fields=DISK_RATE_FIELDS,
        )

    def _sensor_host_available(self):
        """判断 SensorHost 是否正在优先提供磁盘读写速率指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker("disk_rate"))
