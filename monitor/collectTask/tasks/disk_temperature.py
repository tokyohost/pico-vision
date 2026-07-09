"""磁盘温度采集任务。"""

from ..system_tasks import CollectionTask
from .disk_common import DISK_TEMPERATURE_FIELDS, collect_shared_disk_details, publish_disk_snapshot


class DiskTemperatureTask(CollectionTask):
    """采集磁盘温度，并合并到已有磁盘容量和读写速率快照。"""

    name = "disk_temperature"
    zh_name = "磁盘温度采集"
    default_interval = 5.0
    order = 31

    def collect(self):
        """返回合并后的磁盘温度指标。"""
        if self._sensor_host_available():
            return {}
        disks = collect_shared_disk_details(self.collector, refresh_hardware=True)
        if self._sensor_host_available():
            return {}
        return publish_disk_snapshot(
            self.collector,
            disks=disks,
            physical_disks=self.collector._physical_disk_statistics(disks),
            disk_fields=DISK_TEMPERATURE_FIELDS,
            physical_fields=DISK_TEMPERATURE_FIELDS,
        )

    def _sensor_host_available(self):
        """判断 SensorHost 是否正在优先提供磁盘温度指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker("disk_temperature"))
