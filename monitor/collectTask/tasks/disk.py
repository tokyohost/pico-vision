"""磁盘采集任务。"""

from ..system_tasks import CollectionTask


class DiskTask(CollectionTask):
    """采集磁盘容量、健康度、温度和实时读写速率。"""

    name = "磁盘采集"
    default_interval = 15.0
    order = 30

    def collect(self):
        """返回汇总磁盘、逻辑磁盘和物理磁盘指标。"""
        self.collector._refresh_disk_hardware_state()
        disks = self.collector._disk_rates(self.collector._disk_details())
        used_bytes, total_bytes, percent = self.collector._disk_usage(disks)
        return {
            "disk": {
                "percent": percent,
                "used_bytes": used_bytes,
                "total_bytes": total_bytes,
            },
            "disks": disks,
            "physical_disks": self.collector._physical_disk_statistics(disks),
        }