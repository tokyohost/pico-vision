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
    order = 15

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
            if cpu.get("percent") is not None:
                self._mark_available("cpu")
        memory = self._memory_fragment(snapshot.get("memory") or {})
        if memory:
            fragment["memory"] = memory
            has_memory_usage = memory.get("used_bytes") is not None and memory.get("total_bytes") is not None
            if memory.get("percent") is not None or has_memory_usage:
                self._mark_available("memory")
        gpu = self._gpu_fragment(snapshot.get("gpu") or {})
        if gpu is not None:
            fragment["gpu"] = gpu
            if gpu.get("percent") is not None:
                self._mark_available("gpu")
        power = self._power_fragment(snapshot.get("power") or {})
        if power:
            fragment["power"] = power
            self._mark_available("power")
        disk_fragment = self._disk_fragment(snapshot.get("disks") or [])
        fragment.update(disk_fragment)
        return fragment

    def _cpu_fragment(self, cpu):
        """把 SensorHost CPU 数据转换为完整 CPU 快照片段。"""
        percent = self._number(cpu.get("percent"))
        frequency_ghz = self._number(cpu.get("frequency_ghz"))
        temperature_c = self._number(cpu.get("temperature_c"))
        if percent is None and frequency_ghz is None and temperature_c is None:
            return None
        if percent is not None:
            update_per_second(
                self.collector.histories["cpu"],
                round(percent, 1),
                self.collector.history_states.setdefault("cpu", {}),
                time.monotonic(),
            )
        return {
            "percent": percent,
            "frequency_ghz": frequency_ghz,
            "temperature_c": temperature_c,
            "history": list(self.collector.histories["cpu"]),
        }

    def _memory_fragment(self, memory):
        """把 SensorHost 内存数据转换为 monitor 内存快照片段。"""
        percent = self._number(memory.get("percent"))
        used_bytes = self._integer(memory.get("used_bytes"))
        available_bytes = self._integer(memory.get("available_bytes"))
        total_bytes = used_bytes + available_bytes if used_bytes is not None and available_bytes is not None else None
        if percent is None and used_bytes is None and total_bytes is None:
            return None
        if percent is not None:
            update_per_second(
                self.collector.histories["memory"],
                round(percent, 1),
                self.collector.history_states.setdefault("memory", {}),
                time.monotonic(),
            )
        return {
            "percent": percent,
            "used_bytes": used_bytes,
            "total_bytes": total_bytes,
            "history": list(self.collector.histories["memory"]),
        }

    def _gpu_fragment(self, gpu):
        """把 SensorHost GPU 数据转换为 monitor GPU 快照片段。"""
        if not gpu:
            return None
        percent = self._number(gpu.get("percent"))
        temperature_c = self._number(gpu.get("temperature_c"))
        core_clock_mhz = self._number(gpu.get("core_clock_mhz"))
        memory_clock_mhz = self._number(gpu.get("memory_clock_mhz"))
        power_watts = self._number(gpu.get("power_watts"))
        dedicated_memory_used_bytes = self._integer(gpu.get("dedicated_memory_used_bytes"))
        dedicated_memory_total_bytes = self._integer(gpu.get("dedicated_memory_total_bytes"))
        if all(value is None for value in (
            percent,
            temperature_c,
            core_clock_mhz,
            memory_clock_mhz,
            power_watts,
            dedicated_memory_used_bytes,
            dedicated_memory_total_bytes,
        )):
            return None
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
            "temperature_c": temperature_c,
            "core_clock_mhz": core_clock_mhz,
            "memory_clock_mhz": memory_clock_mhz,
            "power_watts": power_watts,
            "dedicated_memory_used_bytes": dedicated_memory_used_bytes,
            "dedicated_memory_total_bytes": dedicated_memory_total_bytes,
            "history": list(self.collector.gpu_history),
            "source": "sensor_host",
        }

    def _power_fragment(self, power):
        """把 SensorHost 功耗数据转换为 monitor 功耗快照片段。"""
        watts = self._number(power.get("watts"))
        if watts is None:
            return None
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

    def _mark_available(self, metric_name):
        """通知采集器指定指标已由 SensorHost 提供。"""
        marker = getattr(self.collector, "mark_sensor_host_metric_available", None)
        if marker is not None:
            marker(metric_name)

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
