"""磁盘容量与健康度采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_CAPACITY_HEALTH_FIELDS, collect_shared_disk_details, publish_disk_snapshot


class DiskCapacityHealthTask(CollectionTask):
    """采集磁盘容量和健康度，低频刷新较重的磁盘基础信息。"""

    name = "disk_capacity_health"
    zh_name = "磁盘容量与健康采集"
    default_interval = 60.0
    order = 30

    def collect(self):
        """返回合并后的磁盘容量、健康度和汇总容量指标。"""
        if self._sensor_host_available():
            return {}
        disks = collect_shared_disk_details(self.collector, refresh_hardware=True)
        if self._sensor_host_available():
            return {}
        used_bytes, total_bytes, percent = self.collector._disk_usage(disks)
        return publish_disk_snapshot(
            self.collector,
            disk={
                "percent": percent,
                "used_bytes": used_bytes,
                "total_bytes": total_bytes,
            },
            disks=disks,
            physical_disks=self.collector._physical_disk_statistics(disks),
            disk_fields=DISK_CAPACITY_HEALTH_FIELDS,
            physical_fields=DISK_CAPACITY_HEALTH_FIELDS,
            replace_disks=True,
            replace_physical_disks=True,
        )

    def _sensor_host_available(self):
        """判断 SensorHost 是否正在优先提供磁盘容量和健康指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and (checker("disk_capacity_health") or checker("disk_space_percent")))
