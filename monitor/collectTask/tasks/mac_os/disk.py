"""处理 macOS APFS 共享容量、物理存储映射、SMART 和 IO 计数。"""

import json
import os
import re
import shutil
import threading
import time
from collections import deque

import psutil

from constants import HISTORY_LENGTH
from history import update_per_second
from monitor_core.collectors.disk import DiskMetricsMixin
from monitor_core.collectors.models import DISK_HEALTH_FAILED, DISK_HEALTH_HEALTHY, DISK_HEALTH_UNKNOWN
from .native import number, read_plist, run_command


def disk_identifier(device):
    """提取 Darwin 设备标识，并把系统卷快照规范化为原始卷标识。"""
    match = re.fullmatch(r"(?:/dev/)?r?(disk\d+(?:s\d+)*)", str(device or ""))
    if not match:
        return None
    name = match.group(1)
    # 根卷通常为 disk3s1s1，它是 disk3s1 的只读快照。
    return re.sub(r"^(disk\d+s\d+)s\d+$", r"\1", name)


class MacOsDiskMetrics:
    """为磁盘任务提供线程安全、低频拓扑与传感器缓存。"""

    def __init__(self, collector):
        """保存历史序列拥有者，并初始化磁盘拓扑和 SMART 缓存。"""
        self.collector = collector
        self._lock = threading.RLock()
        self._signature = None
        self._topology_at = 0.0
        self._containers = {}
        self._infos = {}
        self._smart_cache = {}
        self._smartctl = None
        self._smartctl_checked = False

    def _refresh_topology(self, partitions):
        """按 APFS 容器关联物理存储，挂载变化或一分钟到期后重新查询。"""
        signature = tuple(sorted((part.device, part.mountpoint, part.fstype) for part in partitions))
        now = time.monotonic()
        if signature == self._signature and now - self._topology_at < 60:
            return
        if signature != self._signature:
            self._smart_cache.clear()
        self._signature, self._topology_at = signature, now
        self._containers, self._infos = {}, {}
        payload = read_plist(["/usr/sbin/diskutil", "apfs", "list", "-plist"])
        for container in payload.get("Containers", []) if isinstance(payload, dict) else []:
            if not isinstance(container, dict):
                continue
            reference = disk_identifier(container.get("ContainerReference"))
            stores = sorted({disk_identifier(store.get("DeviceIdentifier", "")) for store in container.get("PhysicalStores", [])
                             if isinstance(store, dict)} - {None})
            physical = sorted({re.match(r"disk\d+", store).group() for store in stores})
            capacity = number(container.get("CapacityCeiling"), minimum=1)
            free = number(container.get("CapacityFree"))
            mapping = {"key": reference, "physical": physical, "total": capacity, "free": free}
            if reference:
                self._containers[reference] = mapping
            for volume in container.get("Volumes", []):
                if isinstance(volume, dict):
                    identifier = disk_identifier(volume.get("DeviceIdentifier"))
                    if identifier:
                        self._containers[identifier] = mapping

    def _info(self, identifier):
        """缓存 diskutil info 查询，同一拓扑周期只读取每个设备一次。"""
        if identifier not in self._infos:
            payload = read_plist(["/usr/sbin/diskutil", "info", "-plist", identifier], timeout=2)
            self._infos[identifier] = payload if isinstance(payload, dict) else {}
        return self._infos[identifier]

    def _sensor(self, physical):
        """优先使用 smartctl JSON；未安装或无权限时退回 diskutil SMART 状态。"""
        now = time.monotonic()
        previous = self._smart_cache.get(physical)
        if previous and now - previous[0] < 30:
            return previous[1]
        info = self._info(physical)
        status = str(info.get("SMARTStatus", "")).lower()
        health = DISK_HEALTH_HEALTHY if status == "verified" else DISK_HEALTH_FAILED if status == "failing" else DISK_HEALTH_UNKNOWN
        sensor = {"health": health, "temperature_c": None}
        if not self._smartctl_checked:
            self._smartctl_checked = True
            self._smartctl = shutil.which("smartctl")
            if self._smartctl is None:
                self._smartctl = next((path for path in ("/opt/homebrew/sbin/smartctl", "/usr/local/sbin/smartctl")
                                       if os.path.isfile(path)), None)
        if self._smartctl:
            result = run_command([self._smartctl, "-a", "-j", "/dev/" + physical], timeout=2)
            if result is not None:
                try:
                    payload = json.loads(result.stdout)
                    # smartctl 非零退出码也可能包含磁盘故障的有效 SMART 数据。
                    if isinstance(payload, dict):
                        parsed_health = DiskMetricsMixin._classify_smart_health(payload)
                        if parsed_health != DISK_HEALTH_UNKNOWN:
                            sensor["health"] = parsed_health
                        nvme = payload.get("nvme_smart_health_information_log", {})
                        raw_temperature = payload.get("temperature", {}).get("current", nvme.get("temperature"))
                        sensor["temperature_c"] = DiskMetricsMixin._normalize_temperature(raw_temperature)
                except (ValueError, TypeError, AttributeError, UnicodeError):
                    pass
        self._smart_cache[physical] = (now, sensor)
        return sensor

    def details(self):
        """按容量池去重 APFS 卷与快照，再汇总到不重复的物理存储组。"""
        with self._lock:
            try:
                partitions = psutil.disk_partitions(all=False)
            except (OSError, psutil.Error):
                return []
            self._refresh_topology(partitions)
            pools = {}
            for partition in partitions:
                identifier = disk_identifier(partition.device)
                if not identifier or "cdrom" in partition.opts.lower().split(","):
                    continue
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                except (OSError, psutil.Error):
                    continue
                if usage.total <= 0:
                    continue
                mapping = self._containers.get(identifier)
                info = self._info(identifier) if mapping is None else {}
                if mapping is None and str(partition.fstype).lower() == "apfs":
                    reference = disk_identifier(info.get("APFSContainerReference"))
                    container_info = self._info(reference) if reference else info
                    stores = container_info.get("APFSPhysicalStores", [])
                    physical = []
                    for store in stores if isinstance(stores, list) else []:
                        store_name = disk_identifier(store.get("DeviceIdentifier")) if isinstance(store, dict) else disk_identifier(store)
                        if store_name:
                            physical.append(re.match(r"disk\d+", store_name).group())
                    if physical:
                        mapping = {"key": reference or identifier, "physical": sorted(set(physical)),
                                   "total": None, "free": None}
                # 排除 DMG 等虚拟介质；不使用 diskN 数字规则猜测 APFS 物理盘。
                if info.get("VirtualOrPhysical") == "Virtual" and not mapping and str(partition.fstype).lower() != "apfs":
                    continue
                if mapping:
                    key = mapping["key"] or re.match(r"disk\d+", identifier).group()
                    physical = mapping["physical"] or [key]
                    total = mapping["total"] if mapping["total"] is not None else usage.total
                    free = mapping["free"] if mapping["free"] is not None else usage.free
                else:
                    key = info.get("APFSContainerReference") or identifier
                    # diskutil 不可用时按 APFS synthesized disk 去重，而非把各卷重复求和。
                    if str(partition.fstype).lower() == "apfs":
                        key = re.match(r"disk\d+", identifier).group()
                    physical = [info.get("ParentWholeDisk") or re.match(r"disk\d+", identifier).group()]
                    total, free = usage.total, usage.free
                pool = pools.setdefault(key, {"physical": physical, "total": int(total), "free": int(free),
                                               "devices": set(), "mountpoints": set(), "filesystems": set(),
                                               "backing_known": bool(mapping and mapping["physical"])})
                # 容器查询失败时多个卷的可用空间略有差异，使用最大已用值但绝不累加共享容量。
                pool["total"] = max(pool["total"], int(total))
                pool["free"] = min(pool["free"], int(free))
                pool["devices"].add("/dev/" + identifier)
                pool["mountpoints"].add(partition.mountpoint)
                pool["filesystems"].add(partition.fstype)
            groups = {}
            for pool in pools.values():
                name = "+".join(pool["physical"])
                group = groups.setdefault(name, {"name": name, "devices": set(pool["physical"]), "mountpoints": set(),
                                                 "filesystems": set(), "total_bytes": 0, "free_bytes": 0,
                                                 "_backing_known": False})
                group["_backing_known"] = group["_backing_known"] or pool["backing_known"]
                group["devices"].update(pool["devices"])
                group["mountpoints"].update(pool["mountpoints"])
                group["filesystems"].update(pool["filesystems"])
                group["total_bytes"] += pool["total"]
                group["free_bytes"] += max(0, min(pool["total"], pool["free"]))
            disks = []
            for name, group in sorted(groups.items()):
                # APFS 磁盘映像也有容器，需检查实际 backing store，而非把所有 APFS 都当物理盘。
                backing_infos = [self._info(physical) for physical in name.split("+")]
                if group.pop("_backing_known") and any(info.get("VirtualOrPhysical") == "Virtual" for info in backing_infos):
                    continue
                sensors = [self._sensor(physical) for physical in name.split("+")]
                temperatures = [sensor["temperature_c"] for sensor in sensors if sensor["temperature_c"] is not None]
                group.update(used_bytes=group["total_bytes"] - group["free_bytes"],
                             temperature_c=max(temperatures) if temperatures else None,
                             health=max((sensor["health"] for sensor in sensors), default=DISK_HEALTH_UNKNOWN))
                if group["health"] == DISK_HEALTH_HEALTHY and any(sensor["health"] == DISK_HEALTH_UNKNOWN for sensor in sensors):
                    group["health"] = DISK_HEALTH_UNKNOWN
                group["percent"] = round(group["used_bytes"] * 100 / group["total_bytes"], 1) if group["total_bytes"] else 0
                for field in ("devices", "mountpoints", "filesystems"):
                    group[field] = sorted(group[field])
                disks.append(group)
            return disks

    def rates(self, disks):
        """使用物理 diskN 计数器计算速率，支持 Fusion Drive 多存储组与计数器重置。"""
        with self._lock:
            owner = self.collector
            now = time.monotonic()
            try:
                counters = psutil.disk_io_counters(perdisk=True) or {}
            except (OSError, RuntimeError, psutil.Error):
                counters = {}
            previous = owner.last_disk_io or {}
            elapsed = now - owner.last_disk_io_time if owner.last_disk_io_time is not None else 0
            results = []
            for disk in disks:
                disk = dict(disk)
                read_bps = write_bps = 0
                for physical in str(disk["name"]).split("+"):
                    current, old = counters.get(physical), previous.get(physical)
                    if current is not None and old is not None and elapsed > 0:
                        read_bps += round(max(0, current.read_bytes - old.read_bytes) / elapsed)
                        write_bps += round(max(0, current.write_bytes - old.write_bytes) / elapsed)
                histories = owner.disk_io_histories.setdefault(disk["name"], {})
                for kind, value in (("read", read_bps), ("write", write_bps)):
                    history = histories.setdefault(kind, deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH))
                    update_per_second(history, value, histories.setdefault(kind + "_state", {}), now)
                    disk[kind + "_bps"] = value
                    disk[kind + "_history"] = list(history)
                results.append(disk)
            owner.last_disk_io, owner.last_disk_io_time = counters, now
            return results
