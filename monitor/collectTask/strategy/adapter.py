"""把 LibreHardwareMonitor 快照适配为采集任务所需的数据片段。"""

from .base import clean_text
from .cpu import CPU_FIELDS
from .disk import DISK_FIELDS
from .gpu import GPU_FIELDS
from .memory import MEMORY_AVAILABLE_BYTES, MEMORY_PERCENT, MEMORY_USED_BYTES
from .power import POWER_SCOPE, POWER_SOURCE, POWER_WATTS


class LibreHardwareMonitorSnapshotAdapter:
    """仅执行纯内存解析，不发起采集、I/O、等待或其他耗时操作。"""

    def parse(self, raw_data, context):
        """使用原始硬件列表和快照上下文解析全部标准字段。"""
        return {
            "cpu": self._parse_cpu(raw_data, context),
            "memory": self._parse_memory(raw_data, context),
            "gpu": self._parse_gpu(raw_data, context),
            "power": self._parse_power(raw_data, context),
            "disks": self._parse_disks(raw_data, context),
        }

    @staticmethod
    def _parse_cpu(raw_data, context):
        """逐字段解析 CPU 数据。"""
        cpu = {
            field: chain.parse(raw_data, context)
            for field, chain in CPU_FIELDS.items()
        }
        return cpu if any(value is not None for value in cpu.values()) else None

    @staticmethod
    def _parse_memory(raw_data, context):
        """只解析物理内存，兼容旧版扁平内存结构。"""
        memory_data = context.get("memory") or {}
        physical_memory = memory_data.get("physical") or memory_data
        memory_context = dict(context)
        memory_context["memory"] = physical_memory
        used_bytes = MEMORY_USED_BYTES.parse(raw_data, memory_context)
        available_bytes = MEMORY_AVAILABLE_BYTES.parse(raw_data, memory_context)
        memory = {
            "percent": MEMORY_PERCENT.parse(raw_data, memory_context),
            "used_bytes": used_bytes,
            "total_bytes": used_bytes + available_bytes
            if used_bytes is not None and available_bytes is not None else None,
        }
        return memory if any(value is not None for value in memory.values()) else None

    @staticmethod
    def _parse_gpu(raw_data, context):
        """逐字段解析 GPU 数据。"""
        if not context.get("gpu"):
            return None
        gpu = {field: chain.parse(raw_data, context) for field, chain in GPU_FIELDS.items()}
        metric_fields = tuple(field for field in gpu if field != "name")
        return gpu if any(gpu[field] is not None for field in metric_fields) else None

    @staticmethod
    def _parse_power(raw_data, context):
        """解析功耗值及其来源和统计范围。"""
        watts = POWER_WATTS.parse(raw_data, context)
        if watts is None:
            return None
        return {
            "watts": watts,
            "source": POWER_SOURCE.parse(raw_data, context) or "sensor_host",
            "scope": POWER_SCOPE.parse(raw_data, context) or "cpu_gpu",
        }

    @staticmethod
    def _parse_disks(raw_data, context):
        """逐盘逐字段解析磁盘数据。"""
        disks = []
        for disk_data in context.get("disks") or ():
            disk_context = dict(context)
            disk_context["disk"] = disk_data
            item = {field: chain.parse(raw_data, disk_context) for field, chain in DISK_FIELDS.items()}
            item["name"] = clean_text(item["name"])
            if item["name"]:
                disks.append(item)
        return disks
