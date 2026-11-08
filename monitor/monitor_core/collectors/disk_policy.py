"""Linux 磁盘休眠保护：以被动活动证据约束所有主动查询。"""

import json
import platform
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import psutil

from .models import LOGGER


class DiskPolicyMixin:
    """管理磁盘查询策略以及保护模式下的容量和健康缓存。"""

    def configure_disk_policy(self, disk_allow_wakeup=True, disk_smart_interval_minutes=30):
        """原子更新策略，不在设置保存线程访问磁盘或重置健康检查时间。"""
        from monitor_core.config import validate_disk_settings
        from collectTask.tasks.disk_common import disk_task_lock

        minutes = validate_disk_settings({
            "disk_allow_wakeup": disk_allow_wakeup,
            "disk_smart_interval_minutes": disk_smart_interval_minutes,
        })
        with disk_task_lock(self):
            previous = getattr(self, "disk_allow_wakeup", True)
            if minutes != getattr(self, "disk_smart_interval_minutes", 30):
                self.disk_temperature_time = 0.0
            self.disk_allow_wakeup = disk_allow_wakeup
            self.disk_smart_interval_minutes = minutes
            self._disk_details_task_cache = None
            if previous != disk_allow_wakeup:
                # 切换后不能把主动模式的数据冒充本次安全采集结果。
                self.disk_temperature_time = 0.0
                self._protected_io_by_task = {}
                self._protected_sensors = {}
                self._protected_seed = [dict(item) for item in getattr(self, "_disk_task_snapshot", {}).get("disks", ())]

    def _protect_disk_sleep(self):
        """仅在 Linux 且用户明确关闭主动唤醒时启用保护。"""
        return platform.system() == "Linux" and not getattr(self, "disk_allow_wakeup", True)

    @staticmethod
    def _safe_ata_type(name):
        """只接受 sysfs 确认的直连 ATA 路径，不探测 USB 或 RAID 桥接。"""
        try:
            parts = (Path("/sys/class/block") / name / "device").resolve(strict=True).parts
        except OSError:
            return None
        if any(part.startswith("usb") for part in parts):
            return None
        return "sat" if any(part.startswith("ata") and part[3:].isdigit() for part in parts) else None

    def _protected_smart(self, name, health_due):
        """受保护地读取已知 ATA 设备，状态不支持时直接退出，禁止主动回退。"""
        device_type = self._safe_ata_type(name)
        if device_type is None:
            return None
        command = ["smartctl", "-n", "standby,3,5", "-d", device_type, "-j"]
        command.extend(["-a"] if health_due else ["-A"])
        command.append("/dev/" + name)
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                    timeout=5, check=False)
            # 低三位表示参数、打开设备或命令执行失败；SMART 告警高位仍可有有效数据。
            if result.returncode & 7:
                return None
            payload = json.loads(result.stdout)
            return payload if isinstance(payload, dict) and any(key in payload for key in ("smart_status", "ata_smart_attributes", "temperature")) else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    def _passive_disk_details(self, collect_sensors=True, collect_capacity=True):
        """被动枚举磁盘，仅在观测到业务 I/O 后尝试安全采集，空闲时不发命令。"""
        now = time.monotonic()
        names = self._list_linux_physical_disks()
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except (OSError, RuntimeError):
            counters = {}
        current = {name: (item.read_bytes, item.write_bytes) for name, item in counters.items()}
        task_key = "capacity" if collect_capacity else "temperature"
        io_by_task = getattr(self, "_protected_io_by_task", {})
        previous = io_by_task.get(task_key, {})
        active = {name for name in names if name in previous and name in current
                  and previous[name] != current[name]}
        io_by_task[task_key] = current
        self._protected_io_by_task = io_by_task
        sensors = getattr(self, "_protected_sensors", {})
        health_times = getattr(self, "_protected_health_times", {})
        health_values = getattr(self, "_protected_health_values", {})
        attempts_by_task = getattr(self, "_protected_attempts_by_task", {})
        attempts = attempts_by_task.setdefault(task_key, {})
        failures = getattr(self, "_protected_failures", {})
        interval = getattr(self, "disk_smart_interval_minutes", 30) * 60
        safe = set()
        for name in names:
            if name not in active:
                sensors[name] = {"temperature_c": None, "health": 0}
                continue
            if (not collect_sensors or now < failures.get(name, 0)
                    or now - attempts.get(name, -float("inf")) < 30):
                continue
            attempts[name] = now
            due = name not in health_times or now - health_times[name] >= interval
            payload = self._protected_smart(name, due)
            if payload is None:
                # 失败退避跨温度和容量任务共享，避免两个任务连续重试同一设备。
                failures[name] = now + 30
                sensors[name] = {"temperature_c": None, "health": 0}
                continue
            failures.pop(name, None)
            safe.add(name)
            sensor = sensors.setdefault(name, {})
            sensor["temperature_c"] = self._normalize_temperature(payload.get("temperature", {}).get("current"))
            if due:
                status = self._classify_smart_health(payload)
                if status:
                    health_values[name] = status
                    health_times[name] = now
                    if status >= 2:
                        LOGGER.warning("磁盘 SMART 健康告警：磁盘=%s，health=%d", name, status)
            sensor["health"] = health_values.get(name, 0)
        self._protected_sensors = {name: sensors[name] for name in names if name in sensors}
        self._protected_health_values = {name: value for name, value in health_values.items() if name in names}
        self._protected_health_times = {name: stamp for name, stamp in health_times.items() if name in names}
        attempts_by_task[task_key] = {name: stamp for name, stamp in attempts.items() if name in names}
        self._protected_attempts_by_task = attempts_by_task
        self._protected_failures = {name: until for name, until in failures.items() if name in names}
        capacities = getattr(self, "_protected_capacities", {})
        details = []
        mounted = set()
        selected = {}
        for partition in psutil.disk_partitions(all=False):
            device = str(partition.device)
            backing = set(self._linux_backing_disks(device))
            # 过滤网络、虚拟和无法解析的挂载，避免访问其文件系统。
            if not backing or not backing.issubset(set(names)):
                continue
            old = selected.get(device)
            if old is None or self._mountpoint_rank(partition) < self._mountpoint_rank(old):
                selected[device] = partition
        retained = {}
        for device, partition in selected.items():
            backing = set(self._linux_backing_disks(device))
            key = (device, partition.mountpoint, tuple(sorted(backing)))
            cached = capacities.get(key)
            if cached is None:
                # 切换保护时仅复用可精确对应的单卷缓存，不猜测多分区的容量分摊。
                for seed in getattr(self, "_protected_seed", ()):
                    if seed.get("devices") == [device] and seed.get("mountpoints") == [partition.mountpoint] and seed.get("capacity_updated_at"):
                        cached = (SimpleNamespace(used=seed.get("used_bytes", 0), total=seed.get("total_bytes", 0),
                                                  free=seed.get("free_bytes", 0), percent=seed.get("percent")),
                                  seed["capacity_updated_at"])
                        break
            fresh = False
            # 状态未知或任一 RAID 成员不满足安全条件时，不调用 statvfs。
            if collect_capacity and backing.issubset(safe):
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    cached = (usage, time.time())
                    fresh = True
                except OSError:
                    pass
            retained[key] = cached
            usage, stamp = cached if cached else (None, None)
            logical = len(backing) > 1 or self._linux_block_device_name(device).startswith(("dm-", "md"))
            name = self._linux_block_device_name(device) if logical else next(iter(backing))
            mounted.add(name)
            temperatures = [sensors.get(item, {}).get("temperature_c") for item in backing]
            health = [sensors.get(item, {}).get("health", 0) for item in backing]
            details.append({
                "name": name, "label": partition.mountpoint, "devices": [device],
                "mountpoints": [partition.mountpoint], "filesystems": [partition.fstype],
                "used_bytes": usage.used if usage else 0, "total_bytes": usage.total if usage else 0,
                "free_bytes": usage.free if usage else 0, "percent": usage.percent if usage else None,
                "temperature_c": max((value for value in temperatures if value is not None), default=None),
                "health": max(health) if all(health) or max(health) >= 2 else 0,
                "capacity_stale": not fresh, "capacity_updated_at": stamp,
            })
        self._protected_capacities = retained
        self._protected_seed = []
        # 同一物理盘上的多个分区合并，保留全部挂载点，避免快照按名称覆盖容量。
        grouped = {}
        for disk in details:
            previous_disk = grouped.get(disk["name"])
            if previous_disk is None:
                grouped[disk["name"]] = disk
                continue
            for key in ("used_bytes", "total_bytes", "free_bytes"):
                previous_disk[key] += disk[key]
            for key in ("devices", "mountpoints", "filesystems"):
                previous_disk[key] = sorted(set(previous_disk[key] + disk[key]))
            previous_disk["label"] = ", ".join(previous_disk["mountpoints"])
            previous_disk["capacity_stale"] |= disk["capacity_stale"]
            stamps = (previous_disk["capacity_updated_at"], disk["capacity_updated_at"])
            previous_disk["capacity_updated_at"] = min(stamps) if all(stamps) else None
            total = previous_disk["total_bytes"]
            previous_disk["percent"] = (round(previous_disk["used_bytes"] * 100 / total, 1)
                                         if all(stamps) and total else None)
        details = list(grouped.values())
        for name in names:
            if name not in mounted:
                details.append({
                    "name": name, "label": name, "devices": ["/dev/" + name], "mountpoints": [],
                    "filesystems": [], "used_bytes": 0, "free_bytes": 0,
                    "total_bytes": self._read_linux_disk_capacity(name), "percent": None,
                    "temperature_c": sensors.get(name, {}).get("temperature_c"),
                    "health": sensors.get(name, {}).get("health", 0),
                    "capacity_stale": True, "capacity_updated_at": None,
                })
        return details
