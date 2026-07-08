"""磁盘容量与健康度采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_CAPACITY_HEALTH_FIELDS, publish_disk_snapshot


class DiskCapacityHealthTask(CollectionTask):
    """采集磁盘容量和健康度，低频刷新较重的磁盘基础信息。"""

    name = "磁盘容量与健康采集"
    default_interval = 60.0
    order = 30

    def collect(self):
        """返回合并后的磁盘容量、健康度和汇总容量指标。"""
        self.collector._refresh_disk_hardware_state()
        disks = self.collector._disk_details()
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
