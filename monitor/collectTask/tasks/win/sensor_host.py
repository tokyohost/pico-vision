"""SensorHost 外置硬件传感器采集任务。"""

import time
from collections import deque

from constants import HISTORY_LENGTH
from history import update_per_second

from ...system_tasks import CollectionTask
from ..disk_common import (
    DISK_CAPACITY_HEALTH_FIELDS,
    DISK_RATE_FIELDS,
    DISK_TEMPERATURE_FIELDS,
    publish_disk_snapshot,
)


class SensorHostTask(CollectionTask):
    """通过 C# SensorHost 采集 Windows 硬件温度、GPU、功耗和磁盘传感器。"""

    name = "sensor_host"
    zh_name = "SensorHost硬件传感器采集"
    default_interval = 1.0
    order = 15
    supported_platforms = ("Windows",)

    def collect(self):
        """读取 SensorHost 快照并转换为 monitor 标准字段。"""
        manager = getattr(self.collector, "sensor_host", None)
        if manager is None:
            return {}
        snapshot = manager.snapshot()
        if not snapshot:
            return {}
        fragment = {}
        cpu = self._cpu_fragment(snapshot.get("cpu") or {}, snapshot.get("hardware") or [])
        has_cpu_temperature = False
        if cpu:
            self.collector._sensor_host_cpu_fragment = dict(cpu)
            fragment["cpu"] = cpu
            if cpu.get("percent") is not None:
                self._mark_available("cpu")
            has_cpu_temperature = cpu.get("temperature_c") is not None
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
        if has_cpu_temperature:
            self._mark_available("cpu_temperature")
        disk_fragment = self._disk_fragment(snapshot.get("disks") or [])
        fragment.update(disk_fragment)
        return fragment

    def _cpu_fragment(self, cpu, hardware):
        """把 SensorHost CPU 数据转换为完整 CPU 快照片段。"""
        percent = self._number(cpu.get("percent"))
        frequency_ghz = self._number(cpu.get("frequency_ghz"))
        temperature_c = self._number(cpu.get("temperature_c"))
        if temperature_c is None:
            temperature_c = self._cpu_temperature_from_hardware(hardware)
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
        """把 SensorHost 磁盘容量、健康、温度和读写速率合并到磁盘快照。"""
        if not disks:
            return {}
        disk_items = []
        has_capacity_health = False
        has_temperature = False
        has_rate = False
        for disk in disks:
            name = str(disk.get("name") or "").replace("\x00", "").strip()
            if not name:
                continue
            item = {
                "name": name,
                "temperature_c": self._number(disk.get("temperature_c")),
                "percent": self._number(disk.get("used_space_percent")),
                "health": self._health_level(disk.get("health_percent")),
                "read_bps": self._integer(disk.get("read_bytes_per_second")),
                "write_bps": self._integer(disk.get("write_bytes_per_second")),
            }
            self._append_disk_rate_history(item)
            has_capacity_health = has_capacity_health or item["percent"] is not None or item["health"] is not None
            has_temperature = has_temperature or item["temperature_c"] is not None
            has_rate = has_rate or item["read_bps"] is not None or item["write_bps"] is not None
            disk_items.append(item)
        if not disk_items:
            return {}
        disk_fields = tuple(dict.fromkeys(DISK_CAPACITY_HEALTH_FIELDS + DISK_TEMPERATURE_FIELDS + DISK_RATE_FIELDS))
        if has_capacity_health:
            self._mark_available("disk_space_percent")
        if has_temperature:
            self._mark_available("disk_temperature")
        if has_rate:
            self._mark_available("disk_rate")
        disk = self._disk_summary(disk_items) if has_capacity_health else None
        return publish_disk_snapshot(
            self.collector,
            disk=disk,
            disks=disk_items,
            physical_disks=disk_items,
            disk_fields=disk_fields,
            physical_fields=disk_fields,
            replace_disks=has_capacity_health,
            replace_physical_disks=has_capacity_health,
        )

    @classmethod
    def _cpu_temperature_from_hardware(cls, hardware):
        """从 SensorHost 原始硬件传感器中兜底提取 CPU 温度。"""
        preferred_names = ("CPU Package", "CPU Tctl/Tdie", "Core Max", "CPU")
        candidates = []
        for item in hardware:
            hardware_type = str(item.get("type") or "")
            for sensor in item.get("sensors") or ():
                if str(sensor.get("type") or "") != "Temperature":
                    continue
                name = str(sensor.get("name") or "")
                value = cls._number(sensor.get("value"))
                if value is None:
                    continue
                if hardware_type == "Cpu" or name in preferred_names or name.startswith("CPU"):
                    candidates.append((name, value))
        for preferred in preferred_names:
            for name, value in candidates:
                if name == preferred:
                    return value
        return candidates[0][1] if candidates else None

    def _append_disk_rate_history(self, item):
        """维护 SensorHost 磁盘读写速率历史，保证显示端趋势字段完整。"""
        name = item.get("name") or "DISK"
        disk_io_histories = getattr(self.collector, "disk_io_histories", None)
        if disk_io_histories is None:
            disk_io_histories = {}
            self.collector.disk_io_histories = disk_io_histories
        histories = disk_io_histories.setdefault(name, {})
        now = time.monotonic()
        for field, history_name in (("read_bps", "read"), ("write_bps", "write")):
            value = item.get(field)
            if value is None:
                continue
            history = histories.setdefault(history_name, deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH))
            state = histories.setdefault(history_name + "_state", {})
            update_per_second(history, value, state, now)
            item[history_name + "_history"] = list(history)

    @classmethod
    def _health_level(cls, health_percent):
        """把 SensorHost 健康剩余百分比映射为项目统一的 0 至 5 健康等级。"""
        value = cls._number(health_percent)
        if value is None:
            return None
        if value <= 0:
            return 5
        if value < 10:
            return 4
        if value < 25:
            return 3
        if value < 60:
            return 2
        return 1

    @staticmethod
    def _disk_summary(disks):
        """根据 SensorHost 物理盘占用率生成轻量磁盘汇总。"""
        values = [disk.get("percent") for disk in disks if disk.get("percent") is not None]
        if not values:
            return None
        return {"percent": round(sum(values) / len(values), 1)}

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
