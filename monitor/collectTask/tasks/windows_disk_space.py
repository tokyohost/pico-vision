"""Windows SensorHost 磁盘空间补齐任务。"""

import json
import re
import subprocess

from ..system_tasks import CollectionTask
from .disk_common import DISK_CAPACITY_HEALTH_FIELDS, disk_snapshot_disks, publish_disk_snapshot


class WindowsDiskSpaceTask(CollectionTask):
    """在 SensorHost 已提供磁盘占用百分比时，使用 WMI 补齐容量字节。"""

    name = "windows_disk_space"
    zh_name = "Windows磁盘空间补齐采集"
    default_interval = 60.0
    order = 29
    supported_platforms = ("Windows",)

    def collect(self):
        """根据 SensorHost 百分比和 WMI 总容量计算已用、总量和剩余空间。"""
        if not self._sensor_host_percent_available():
            return {}
        disks = [disk for disk in disk_snapshot_disks(self.collector) if disk.get("percent") is not None]
        if not disks:
            return {}
        sizes = self._disk_drive_sizes()
        if not sizes:
            return {}
        completed = []
        for disk in disks:
            total_bytes = self._match_total_bytes(disk.get("name"), sizes)
            if total_bytes is None or total_bytes <= 0:
                continue
            percent = self._number(disk.get("percent"))
            if percent is None:
                continue
            item = dict(disk)
            used_bytes = round(total_bytes * max(0.0, min(100.0, percent)) / 100.0)
            item["used_bytes"] = int(used_bytes)
            item["total_bytes"] = int(total_bytes)
            item["free_bytes"] = max(0, int(total_bytes) - int(used_bytes))
            completed.append(item)
        if not completed:
            return {}
        self._mark_available("disk_capacity_health")
        return publish_disk_snapshot(
            self.collector,
            disk=self._summary(completed),
            disks=completed,
            physical_disks=completed,
            disk_fields=DISK_CAPACITY_HEALTH_FIELDS,
            physical_fields=DISK_CAPACITY_HEALTH_FIELDS,
        )

    @staticmethod
    def _disk_drive_sizes():
        """通过 Win32_DiskDrive 查询物理硬盘型号和总容量。"""
        script = (
            "Get-CimInstance Win32_DiskDrive | "
            "Select-Object Index,Model,Size | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return []
            payload = json.loads(result.stdout) if result.stdout.strip() else []
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return []
        if isinstance(payload, dict):
            payload = [payload]
        sizes = []
        for item in payload:
            total_bytes = WindowsDiskSpaceTask._integer(item.get("Size"))
            model = str(item.get("Model") or "").replace("\x00", "").strip()
            if model and total_bytes is not None and total_bytes > 0:
                sizes.append({"model": model, "total_bytes": total_bytes})
        return sizes

    @classmethod
    def _match_total_bytes(cls, disk_name, sizes):
        """按型号名称把 SensorHost 磁盘和 WMI 磁盘容量进行宽松匹配。"""
        normalized_name = cls._normalize_name(disk_name)
        if not normalized_name:
            return None
        exact = [item for item in sizes if cls._normalize_name(item["model"]) == normalized_name]
        if exact:
            return exact[0]["total_bytes"]
        contains = [
            item for item in sizes
            if normalized_name in cls._normalize_name(item["model"])
            or cls._normalize_name(item["model"]) in normalized_name
        ]
        return contains[0]["total_bytes"] if contains else None

    @staticmethod
    def _normalize_name(value):
        """规范化磁盘型号文本，提升 SensorHost 与 WMI 名称匹配容错性。"""
        return re.sub(r"[^0-9a-z]+", "", str(value or "").replace("\x00", "").lower())

    @staticmethod
    def _summary(disks):
        """汇总全部已补齐容量的磁盘空间。"""
        total_bytes = sum(int(disk.get("total_bytes", 0) or 0) for disk in disks)
        used_bytes = sum(int(disk.get("used_bytes", 0) or 0) for disk in disks)
        free_bytes = sum(int(disk.get("free_bytes", 0) or 0) for disk in disks)
        percent = round(used_bytes * 100 / total_bytes, 1) if total_bytes else 0
        return {
            "percent": percent,
            "used_bytes": used_bytes,
            "total_bytes": total_bytes,
            "free_bytes": free_bytes,
        }

    def _sensor_host_percent_available(self):
        """判断 SensorHost 是否已经提供磁盘占用百分比。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker("disk_space_percent"))

    def _mark_available(self, metric_name):
        """通知采集器指定磁盘指标已经补齐。"""
        marker = getattr(self.collector, "mark_sensor_host_metric_available", None)
        if marker is not None:
            marker(metric_name)

    @staticmethod
    def _number(value):
        """把输入值转换为浮点数，失败时返回空值。"""
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value):
        """把输入值转换为整数，失败时返回空值。"""
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
