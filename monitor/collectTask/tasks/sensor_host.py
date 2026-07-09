"""SensorHost 外置硬件传感器采集任务。"""

import platform
import time

from history import update_per_second

from ..system_tasks import CollectionTask
from .disk_common import DISK_TEMPERATURE_FIELDS, publish_disk_snapshot


class SensorHostTask(CollectionTask):
    """通过 C# SensorHost 采集 Windows 硬件温度、GPU、功耗和磁盘传感器。"""

    name = "sensor_host"
    zh_name = "SensorHost硬件传感器采集"
    default_interval = 1.0
    order = 25

    def collect(self):
        """读取 SensorHost 快照并转换为 monitor 标准字段。"""
        manager = getattr(self.collector, "sensor_host", None)
        if platform.system() != "Windows" or manager is None:
            return {}
        snapshot = manager.snapshot()
        if not snapshot:
            return {}
        fragment = {}
        cpu = self._cpu_fragment(snapshot.get("cpu") or {})
        if cpu:
            fragment["cpu"] = cpu
        gpu = self._gpu_fragment(snapshot.get("gpu") or {})
        if gpu is not None:
            fragment["gpu"] = gpu
        power = self._power_fragment(snapshot.get("power") or {})
        if power:
            fragment["power"] = power
        disk_fragment = self._disk_fragment(snapshot.get("disks") or [])
        fragment.update(disk_fragment)
        return fragment

    def _cpu_fragment(self, cpu):
        """把 SensorHost CPU 数据转换为完整 CPU 快照片段。"""
        percent = self._number(cpu.get("percent"))
        if percent is not None:
            update_per_second(
                self.collector.histories["cpu"],
                round(percent, 1),
                self.collector.history_states.setdefault("cpu", {}),
                time.monotonic(),
            )
        return {
            "percent": percent,
            "frequency_ghz": self._number(cpu.get("frequency_ghz")),
            "temperature_c": self._number(cpu.get("temperature_c")),
            "history": list(self.collector.histories["cpu"]),
        }

    def _gpu_fragment(self, gpu):
        """把 SensorHost GPU 数据转换为 monitor GPU 快照片段。"""
        if not gpu:
            return None
        percent = self._number(gpu.get("percent"))
        if percent is not None:
            update_per_second(
                self.collector.gpu_history,
                percent,
                self.collector.history_states.setdefault("gpu", {}),
                time.monotonic(),
            )
        return {
            "name": gpu.get("name") or "",
            "percent": percent,
            "temperature_c": self._number(gpu.get("temperature_c")),
            "core_clock_mhz": self._number(gpu.get("core_clock_mhz")),
            "memory_clock_mhz": self._number(gpu.get("memory_clock_mhz")),
            "power_watts": self._number(gpu.get("power_watts")),
            "dedicated_memory_used_bytes": self._integer(gpu.get("dedicated_memory_used_bytes")),
            "dedicated_memory_total_bytes": self._integer(gpu.get("dedicated_memory_total_bytes")),
            "history": list(self.collector.gpu_history),
            "source": "sensor_host",
        }

    def _power_fragment(self, power):
        """把 SensorHost 功耗数据转换为 monitor 功耗快照片段。"""
        watts = self._number(power.get("watts"))
        if watts is not None:
            update_per_second(
                self.collector.power_history,
                watts,
                self.collector.history_states.setdefault("power", {}),
                time.monotonic(),
            )
        return {
            "watts": watts,
            "source": power.get("source") or "sensor_host",
            "scope": power.get("scope") or "cpu_gpu",
            "history": list(self.collector.power_history),
        }

    def _disk_fragment(self, disks):
        """把 SensorHost 磁盘温度合并到磁盘快照。"""
        if not disks:
            return {}
        disk_items = []
        for disk in disks:
            name = str(disk.get("name") or "").strip()
            if not name:
                continue
            disk_items.append({
                "name": name,
                "temperature_c": self._number(disk.get("temperature_c")),
            })
        if not disk_items:
            return {}
        return publish_disk_snapshot(
            self.collector,
            disks=disk_items,
            physical_disks=disk_items,
            disk_fields=DISK_TEMPERATURE_FIELDS,
            physical_fields=DISK_TEMPERATURE_FIELDS,
        )

    @staticmethod
    def _number(value):
        """把输入值转换为浮点数，失败时返回空值。"""
        try:
            return round(float(value), 2) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value):
        """把输入值转换为整数，失败时返回空值。"""
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
