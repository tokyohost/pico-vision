#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.

"""采集磁盘容量、I/O、温度和 SMART 健康状态。"""

import json
import os
import platform
import re
import subprocess
import time
from collections import deque
from pathlib import Path

import psutil

from constants import HISTORY_LENGTH
from history import update_per_second
from monitor_core.collectors.models import (
    DISK_HEALTH_CACHE_SECONDS,
    DISK_HEALTH_CRITICAL,
    DISK_HEALTH_FAILED,
    DISK_HEALTH_HEALTHY,
    DISK_HEALTH_NOTICE,
    DISK_HEALTH_UNKNOWN,
    DISK_HEALTH_WARNING,
    DISK_TEMPERATURE_CACHE_SECONDS,
    LOGGER,
)


WINDOWS_DISK_TEMPERATURE_FAILURE_BACKOFF_SECONDS = 60.0


class DiskMetricsMixin:
    """为系统采集器提供磁盘容量、读写速率、温度和健康状态采集能力。"""

    @classmethod
    def _disk_hardware_signature(cls):
        """生成物理磁盘、分区和挂载关系的稳定签名，用于识别热插拔变化。"""
        partitions = []
        try:
            for partition in psutil.disk_partitions(all=False):
                partitions.append((
                    os.path.normcase(str(partition.device or "")),
                    os.path.normcase(str(partition.mountpoint or "")),
                    str(partition.fstype or "").lower(),
                ))
        except (OSError, psutil.Error):
            partitions = []
        physical_disks = ()
        if platform.system() == "Linux":
            physical_disks = cls._list_linux_physical_disks()
        return tuple(sorted(partitions)), tuple(physical_disks)

    def _refresh_disk_hardware_state(self):
        """检测磁盘硬件变化，并立即使 SMART、健康度和温度缓存失效。"""
        signature = self._disk_hardware_signature()
        previous = getattr(self, "disk_hardware_signature", None)
        self.disk_hardware_signature = signature
        if previous is None or previous == signature:
            return False
        self.disk_temperature_cache = {}
        self.disk_temperature_time = 0.0
        self.windows_disk_temperature_failure_until = 0.0
        self._disk_details_task_cache = None
        self._disk_details_task_cache_time = 0.0
        self.disk_health_cache = {}
        self.disk_health_time = 0.0
        LOGGER.info("检测到磁盘硬件或挂载关系变化，立即重新采集 SMART 与 health 状态")
        return True

    @staticmethod
    def _disk_label(disk):
        """优先以排序去重的挂载路径生成友好名，未挂载时回退到设备名称。"""
        mountpoints = sorted({str(path) for path in disk.get("mountpoints") or () if path})
        return ", ".join(mountpoints) or str(disk.get("name") or "DISK")

    @staticmethod
    def _physical_disk_statistics(disks):
        """从磁盘明细生成发送给 Pico 的物理磁盘容量、温度和读写速度统计。"""
        def nullable_number(value, converter):
            """保留传感器未就绪的空值，并规范化已经采集到的数值。"""
            return None if value is None else converter(value)

        # SensorHost 显式返回 None 时，字典默认值不会生效；未知速率和占用率保留为空。
        # 容量、健康等级和序列沿用缺字段时的协议默认值，避免单块磁盘中断整次采集。
        return [
            {
                "name": disk.get("name", "DISK"),
                "label": disk.get("label") or DiskMetricsMixin._disk_label(disk),
                "devices": list(disk.get("devices") or ()),
                "mountpoints": list(disk.get("mountpoints") or ()),
                "used_bytes": int(disk.get("used_bytes") or 0),
                "total_bytes": int(disk.get("total_bytes") or 0),
                "free_bytes": int(disk.get("free_bytes") or 0),
                "percent": nullable_number(disk.get("percent", 0), float),
                "temperature_c": disk.get("temperature_c"),
                "health": int(disk.get("health") or DISK_HEALTH_UNKNOWN),
                "read_bps": nullable_number(disk.get("read_bps", 0), int),
                "write_bps": nullable_number(disk.get("write_bps", 0), int),
                "read_history": list(disk.get("read_history") or ()),
                "write_history": list(disk.get("write_history") or ()),
            }
            for disk in disks
        ]

    @staticmethod
    def _disk_io_aliases(name):
        """生成物理磁盘名称的跨平台别名，用于关联系统磁盘读写计数器。"""
        text = str(name or "").strip()
        basename = os.path.basename(os.path.realpath(text)).lower()
        aliases = {text.lower(), basename}
        linux_name = DiskMetricsMixin._linux_physical_disk(basename)
        if linux_name:
            aliases.add(linux_name.lower())
        disk_number = re.match(r"^disk\s*(\d+)(?:\s|$)", text, re.IGNORECASE)
        physical_drive = re.match(r"^physicaldrive(\d+)$", basename, re.IGNORECASE)
        if disk_number:
            aliases.add("physicaldrive" + disk_number.group(1))
        if physical_drive:
            aliases.add("disk" + physical_drive.group(1))
        return aliases

    @staticmethod
    def _windows_device_number(device):
        """通过 Windows 设备控制接口查询盘符所属物理磁盘编号，无需管理员权限。"""
        if platform.system() != "Windows":
            return None
        drive_match = re.match(r"^([A-Za-z]):", str(device or ""))
        if not drive_match:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class StorageDeviceNumber(ctypes.Structure):
                """描述 Windows 存储设备类型、物理磁盘编号和分区编号。"""

                _fields_ = [
                    ("device_type", wintypes.DWORD),
                    ("device_number", wintypes.DWORD),
                    ("partition_number", wintypes.DWORD),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW(
                "\\\\.\\" + drive_match.group(1).upper() + ":",
                0,
                0x00000001 | 0x00000002,
                None,
                3,
                0,
                None,
            )
            if handle == wintypes.HANDLE(-1).value:
                return None
            try:
                result = StorageDeviceNumber()
                returned = wintypes.DWORD()
                succeeded = kernel32.DeviceIoControl(
                    handle,
                    0x002D1080,
                    None,
                    0,
                    ctypes.byref(result),
                    ctypes.sizeof(result),
                    ctypes.byref(returned),
                    None,
                )
                return int(result.device_number) if succeeded else None
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, TypeError, ValueError):
            return None

    def _disk_rates(self, disks):
        """计算每块物理磁盘的实时读写字节速度，并维护固定长度历史序列。"""
        disks = [dict(disk) for disk in disks]
        now = time.monotonic()
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except (AttributeError, OSError, RuntimeError):
            counters = {}
        elapsed = now - self.last_disk_io_time if self.last_disk_io_time is not None else 0
        previous = self.last_disk_io or {}
        counter_aliases = {
            alias: counter
            for counter_name, counter in counters.items()
            for alias in self._disk_io_aliases(counter_name)
        }
        previous_aliases = {
            alias: counter
            for counter_name, counter in previous.items()
            for alias in self._disk_io_aliases(counter_name)
        }
        for disk in disks:
            aliases = self._disk_io_aliases(disk.get("name"))
            for device in disk.get("devices", ()):
                aliases.update(self._disk_io_aliases(device))
                device_number = self._windows_device_number(device)
                if device_number is not None:
                    aliases.add("physicaldrive" + str(device_number))
            current_counter = next((counter_aliases[item] for item in aliases if item in counter_aliases), None)
            previous_counter = next((previous_aliases[item] for item in aliases if item in previous_aliases), None)
            read_bps = write_bps = 0
            if elapsed > 0 and current_counter is not None and previous_counter is not None:
                read_bps = round(max(0, current_counter.read_bytes - previous_counter.read_bytes) / elapsed)
                write_bps = round(max(0, current_counter.write_bytes - previous_counter.write_bytes) / elapsed)
            history_key = str(disk.get("name") or "DISK")
            histories = self.disk_io_histories.setdefault(
                history_key,
                {},
            )
            # SensorHost 与普通采集任务并发切换时，缓存可能只初始化了部分字段。
            histories.setdefault(
                "read", deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
            )
            histories.setdefault(
                "write", deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
            )
            histories.setdefault("read_state", {})
            histories.setdefault("write_state", {})
            update_per_second(histories["read"], read_bps, histories["read_state"], now)
            update_per_second(histories["write"], write_bps, histories["write_state"], now)
            disk["read_bps"] = read_bps
            disk["write_bps"] = write_bps
            disk["read_history"] = list(histories["read"])
            disk["write_history"] = list(histories["write"])
        self.last_disk_io = counters
        self.last_disk_io_time = now
        return disks

    @staticmethod
    def _normalize_temperature(value):
        """校验并规范化磁盘温度，过滤无效传感器读数。"""
        try:
            temperature = float(value)
        except (TypeError, ValueError):
            return None
        if 0 < temperature < 150:
            return round(temperature, 1)
        return None

    @staticmethod
    def _linux_block_device_name(device):
        """解析块设备名称，在 udev 别名缺失时通过 sysfs 查找 LVM 内核设备。"""
        device = str(device)
        name = os.path.basename(os.path.realpath(device))
        if os.path.dirname(device) != "/dev/mapper" or re.fullmatch(r"dm-\d+", name):
            return name
        # NAS 和容器可能只保留 mapper/control；dm/name 仍保存完整且已转义的卷名。
        try:
            for block_path in Path("/sys/class/block").glob("dm-*"):
                try:
                    mapper_name = (block_path / "dm" / "name").read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if mapper_name == name:
                    return block_path.name
        except OSError:
            pass
        return name

    @classmethod
    def _linux_physical_disk(cls, device):
        """将 Linux 分区设备名称转换为对应的物理块设备名称。"""
        name = cls._linux_block_device_name(device)
        if os.path.dirname(str(device)) == "/dev/mapper" and not re.fullmatch(r"dm-\d+", name):
            return name
        match = re.fullmatch(r"(nvme\d+n\d+|mmcblk\d+)(?:p\d+)?", name)
        if match:
            return match.group(1)
        if re.fullmatch(r"(?:dm-|md|nvme)\d+", name):
            return name
        match = re.match(r"^(.+?)\d+$", name)
        return match.group(1) if match else name

    @classmethod
    def _linux_backing_disks(cls, device):
        """递归解析 Linux 逻辑块设备，返回去重后的底层物理磁盘名称。"""
        ignored_prefixes = ("loop", "ram", "zram", "fd", "sr")
        pending = [cls._linux_physical_disk(device)]
        visited = set()
        physical_disks = set()
        while pending:
            disk_name = pending.pop()
            if not disk_name or disk_name in visited:
                continue
            visited.add(disk_name)
            slave_root = Path("/sys/class/block") / disk_name / "slaves"
            try:
                slaves = tuple(slave_root.iterdir())
            except OSError:
                slaves = ()
            if slaves:
                pending.extend(cls._linux_physical_disk(slave.name) for slave in slaves)
                continue
            normalized_name = cls._linux_physical_disk(disk_name)
            if not normalized_name.startswith(ignored_prefixes):
                physical_disks.add(normalized_name)
        return tuple(sorted(physical_disks))

    @staticmethod
    def _natural_sort_key(text):
        """生成包含数字的 Linux 磁盘名称自然排序键。"""
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]

    @classmethod
    def _list_linux_physical_disks(cls):
        """通过 sysfs 枚举全部物理磁盘，并将逻辑设备解析到底层磁盘。"""
        names = set()
        ignored_prefixes = ("loop", "ram", "zram", "fd", "sr")
        block_root = Path("/sys/class/block")
        try:
            block_paths = tuple(block_root.iterdir())
        except OSError:
            block_paths = ()
        for block_path in block_paths:
            disk_name = block_path.name
            if disk_name.startswith(ignored_prefixes) or (block_path / "partition").exists():
                continue
            try:
                sector_count = int((block_path / "size").read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            if sector_count > 0:
                names.update(cls._linux_backing_disks(disk_name))
        return tuple(sorted(names, key=cls._natural_sort_key))

    @staticmethod
    def _read_linux_disk_capacity(disk_name):
        """通过 sysfs 读取物理块设备总容量，无需挂载点、设备节点或 SMART 权限。"""
        try:
            # size 始终使用 512 字节扇区；4Kn 设备也不能乘逻辑扇区大小。
            sector_count = int((Path("/sys/class/block") / disk_name / "size").read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            # 热拔出、权限不足或内核未提供容量时，保留传感器条目并沿用未知值。
            return 0
        return max(0, sector_count) * 512

    @classmethod
    def _scan_linux_smart_devices(cls):
        """使用 smartctl 自动发现 SATA、NVMe、SCSI 与 RAID 控制器磁盘。"""
        try:
            result = subprocess.run(
                ["smartctl", "--scan-open", "-j"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=5, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {}
        devices = {}
        namespaces = {}
        # 控制器不是块设备；先收集实际命名空间，避免扫描顺序导致重复或虚构 n1。
        namespace_names = [os.path.basename(str(item.get("name", ""))) for item in payload.get("devices", ())]
        try:
            namespace_names.extend(path.name for path in Path("/sys/class/block").glob("nvme*"))
        except OSError:
            pass
        for name in namespace_names:
            match = re.fullmatch(r"(nvme\d+)n\d+", name)
            if match:
                namespaces.setdefault(match.group(1), set()).add(name)
        for device in payload.get("devices", ()):
            device_path = str(device.get("name", "")).strip()
            device_type = str(device.get("type", "")).strip() or None
            if not device_path or device.get("open_error"):
                continue
            path_name = os.path.basename(device_path)
            if re.fullmatch(r"nvme\d+", path_name):
                for disk_name in sorted(namespaces.get(path_name, {path_name + "n1"}), key=cls._natural_sort_key):
                    devices.setdefault(disk_name, (device_path, device_type))
                continue
            elif path_name.isdigit() and device_type:
                disk_name = "".join(re.findall(r"[A-Za-z0-9]+", device_type)) or "disk" + path_name
            else:
                disk_name = cls._linux_physical_disk(device_path)
            if disk_name:
                # 显式命名空间优先于控制器路径，反向扫描也不能覆盖已选择的块设备。
                devices[disk_name] = (device_path, device_type)
        return devices

    @classmethod
    def _discover_linux_disks(cls):
        """合并 sysfs 与 SMART 扫描结果，返回全部 Linux 物理磁盘描述。"""
        smart_devices = cls._scan_linux_smart_devices()
        disk_names = set(cls._list_linux_physical_disks())
        disk_names.update(smart_devices)
        return [
            (disk_name, *smart_devices.get(disk_name, ("/dev/" + disk_name, None)))
            for disk_name in sorted(disk_names, key=cls._natural_sort_key)
        ]

    @staticmethod
    def _smart_attribute_raw_value(attribute):
        """从 smartctl 属性中提取可比较的原始整数值。"""
        raw_value = attribute.get("raw", {}).get("value")
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            match = re.search(r"-?\d+", str(raw_value or ""))
            return int(match.group()) if match else 0

    @classmethod
    def _classify_smart_health(cls, payload):
        """按照 smartmontools 公开指标把 SMART 数据划分为六级健康状态。"""
        if not isinstance(payload, dict) or not payload:
            return DISK_HEALTH_UNKNOWN
        smart_status = payload.get("smart_status", {})
        if smart_status.get("passed") is False:
            return DISK_HEALTH_FAILED

        attributes = payload.get("ata_smart_attributes", {}).get("table", ())
        raw_values = {
            str(attribute.get("name", "")).lower(): cls._smart_attribute_raw_value(attribute)
            for attribute in attributes
        }
        if any(str(attribute.get("when_failed", "")).strip() not in ("", "-") for attribute in attributes):
            return DISK_HEALTH_FAILED

        nvme = payload.get("nvme_smart_health_information_log", {})
        critical_warning = int(nvme.get("critical_warning", 0) or 0)
        if critical_warning & 0x0C:
            return DISK_HEALTH_FAILED
        if critical_warning:
            return DISK_HEALTH_CRITICAL

        percentage_used = int(nvme.get("percentage_used", 0) or 0)
        media_errors = int(nvme.get("media_errors", 0) or 0)
        pending = raw_values.get("current_pending_sector", 0)
        offline_uncorrectable = raw_values.get("offline_uncorrectable", 0)
        reallocated = raw_values.get("reallocated_sector_ct", 0)
        reported_uncorrectable = raw_values.get("reported_uncorrect", 0)
        if percentage_used >= 100 or pending >= 100 or offline_uncorrectable >= 100:
            return DISK_HEALTH_CRITICAL
        if pending or offline_uncorrectable or media_errors >= 100 or reallocated >= 100:
            return DISK_HEALTH_WARNING
        if reallocated or reported_uncorrectable or media_errors or percentage_used >= 90:
            return DISK_HEALTH_NOTICE
        return DISK_HEALTH_HEALTHY if smart_status.get("passed") is True or nvme or attributes else DISK_HEALTH_UNKNOWN

    @classmethod
    def _read_smart_health(cls, device, device_type=None):
        """调用 smartctl 读取单块物理磁盘并返回标准化健康等级。"""
        command = ["smartctl", "-a", "-j"]
        if device_type:
            command.extend(["-d", str(device_type)])
        command.append(str(device))
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, errors="replace", timeout=10,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return DISK_HEALTH_UNKNOWN
        return cls._classify_smart_health(payload)

    def _disk_health(self, descriptors):
        """启动时读取 SMART 健康状态，之后以三十分钟周期复用检查结果。"""
        now = time.monotonic()
        last_time = getattr(self, "disk_health_time", 0.0)
        if last_time and now - last_time < DISK_HEALTH_CACHE_SECONDS:
            return getattr(self, "disk_health_cache", {})
        health = {}
        for name, device, device_type in descriptors:
            status = self._read_smart_health(device, device_type)
            namespace = re.fullmatch(r"/dev/(nvme\d+)n\d+", str(device))
            if status == DISK_HEALTH_UNKNOWN and namespace:
                # 部分驱动只允许通过控制器读取 SMART；仅未知状态需要回退。
                status = self._read_smart_health("/dev/" + namespace.group(1), device_type or "nvme")
            health[name] = status
        for name, status in health.items():
            if status >= DISK_HEALTH_NOTICE:
                LOGGER.warning("磁盘 SMART 健康告警：磁盘=%s，health=%d", name, status)
        self.disk_health_cache = health
        self.disk_health_time = now
        return health

    @classmethod
    def _read_linux_temperature_file(cls, path):
        """读取 Linux 温度文件，并兼容摄氏度与千分之一摄氏度单位。"""
        try:
            value = float(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None
        if abs(value) >= 1000:
            value /= 1000
        return cls._normalize_temperature(value)

    @classmethod
    def _read_linux_disk_temperature(cls, device, device_type=None, disk_name=None):
        """从 Linux hwmon 或 smartctl 读取指定物理磁盘温度。"""
        disk_name = disk_name or cls._linux_physical_disk(device)
        block_path = Path("/sys/class/block") / disk_name
        candidates = []
        for direct_path in (block_path / "device" / "temperature", block_path / "device" / "temp"):
            temperature = cls._read_linux_temperature_file(direct_path)
            if temperature is not None:
                candidates.append((3, temperature))
        hwmon_roots = (block_path / "device" / "hwmon", block_path / "device" / "device" / "hwmon")
        for hwmon_root in hwmon_roots:
            try:
                temperature_paths = tuple(hwmon_root.glob("hwmon*/temp*_input"))
            except OSError:
                temperature_paths = ()
            for temperature_path in temperature_paths:
                temperature = cls._read_linux_temperature_file(temperature_path)
                if temperature is None:
                    continue
                label_path = temperature_path.with_name(temperature_path.name.replace("_input", "_label"))
                try:
                    label = label_path.read_text(encoding="utf-8", errors="replace").strip().lower()
                except OSError:
                    label = ""
                priority = 3 if "composite" in label else 2 if "drive" in label else 1
                candidates.append((priority, temperature))
        if candidates:
            priority = max(item[0] for item in candidates)
            values = [temperature for item_priority, temperature in candidates if item_priority == priority]
            return round(sum(values) / len(values), 1)
        try:
            command = ["smartctl", "-a", "-j"]
            if device_type:
                command.extend(["-d", str(device_type)])
            command.append(str(device))
            result = subprocess.run(
                command,
                capture_output=True, text=True, errors="replace", timeout=5,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        direct_values = (
            payload.get("temperature", {}).get("current"),
            payload.get("nvme_smart_health_information_log", {}).get("temperature"),
        )
        for raw_value in direct_values:
            temperature = cls._normalize_temperature(raw_value)
            if temperature is not None:
                return temperature
        temperature_names = ("temperature_celsius", "airflow_temperature_cel", "temperature_internal")
        attributes = payload.get("ata_smart_attributes", {}).get("table", ())
        for attribute in attributes:
            if str(attribute.get("name", "")).lower() not in temperature_names:
                continue
            temperature = cls._normalize_temperature(attribute.get("raw", {}).get("value"))
            if temperature is not None:
                return temperature
        return None

    @classmethod
    def _read_unassigned_disk_temperatures(cls):
        """读取无法通过块设备路径直接关联的 NVMe 与 drivetemp 温度。"""
        try:
            groups = psutil.sensors_temperatures()
        except (AttributeError, OSError, RuntimeError):
            groups = {}
        values = []
        for group_name in ("nvme", "drivetemp"):
            for entry in groups.get(group_name, ()):
                temperature = cls._normalize_temperature(entry.current)
                if temperature is None:
                    continue
                label = str(entry.label or "").lower()
                values.append((2 if "composite" in label else 1, temperature))
        if not values:
            return []
        priority = max(item[0] for item in values)
        return [temperature for item_priority, temperature in values if item_priority == priority]

    def _windows_disk_temperatures(self):
        """通过 PowerShell 建立 Windows 盘符到物理磁盘温度的映射。"""
        now = time.monotonic()
        failure_until = float(getattr(self, "windows_disk_temperature_failure_until", 0.0) or 0.0)
        if now < failure_until:
            return dict(getattr(self, "disk_temperature_cache", {}) or {})
        script = (
            "$items=@(); Get-Partition | Where-Object DriveLetter | ForEach-Object {"
            "$p=$_; $d=$p | Get-Disk; $diskText=([string]$d.FriendlyName + ' ' + [string]$d.Model);"
            "$virtual=([string]$d.BusType -in @('Virtual','File Backed Virtual')) -or ($diskText -match '(?i)virtual|vmware|vbox|qemu|hyper-v');"
            "$physical=$null; if(-not $virtual){$physical=Get-PhysicalDisk -ErrorAction SilentlyContinue | Where-Object DeviceId -eq ([string]$d.Number) | Select-Object -First 1};"
            "$temperature=$null; if($physical){try{$temperature=($physical | Get-StorageReliabilityCounter -ErrorAction Stop).Temperature}catch{}};"
            "$health=0; if($physical){$health=switch([string]$physical.HealthStatus){'Healthy'{1}'Warning'{3}'Unhealthy'{5}default{0}}};"
            "$items += [pscustomobject]@{Device=([string]$p.DriveLetter + ':');DiskName=('DISK' + [string]$d.Number + ' ' + [string]$d.FriendlyName);Temperature=$temperature;Health=$health}"
            "}; $items | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, errors="replace", timeout=15,
                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "PowerShell 无输出").strip())
            payload = json.loads(result.stdout) if result.stdout.strip() else []
        except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            self.windows_disk_temperature_failure_until = now + WINDOWS_DISK_TEMPERATURE_FAILURE_BACKOFF_SECONDS
            LOGGER.warning(
                "Windows 磁盘温度 PowerShell 采集失败，%.0f秒内复用上次结果：%s",
                WINDOWS_DISK_TEMPERATURE_FAILURE_BACKOFF_SECONDS,
                error,
            )
            return dict(getattr(self, "disk_temperature_cache", {}) or {})
        self.windows_disk_temperature_failure_until = 0.0
        if isinstance(payload, dict):
            payload = [payload]
        temperatures = {}
        for item in payload:
            device = os.path.normcase(str(item.get("Device", "")))
            temperatures[device] = {
                "name": str(item.get("DiskName") or item.get("Device") or "DISK"),
                "temperature_c": self._normalize_temperature(item.get("Temperature")),
                "health": int(item.get("Health", DISK_HEALTH_UNKNOWN) or DISK_HEALTH_UNKNOWN),
            }
        return temperatures

    def _disk_temperatures(self, devices):
        """按固定周期缓存全部磁盘温度，避免每帧调用慢速系统接口。"""
        now = time.monotonic()
        if self.disk_temperature_time and now - self.disk_temperature_time < DISK_TEMPERATURE_CACHE_SECONDS:
            return self.disk_temperature_cache
        if platform.system() == "Windows":
            temperatures = self._windows_disk_temperatures()
        elif platform.system() == "Linux":
            temperatures = {}
            descriptors = self._discover_linux_disks()
            health_by_name = self._disk_health(descriptors)
            disk_sensors_by_name = {}
            missing_names = []
            for physical_name, device_path, device_type in descriptors:
                temperature = self._read_linux_disk_temperature(device_path, device_type, physical_name)
                disk_sensors_by_name[physical_name] = {
                    "name": physical_name,
                    "device": device_path,
                    "temperature_c": temperature,
                    "health": health_by_name.get(physical_name, DISK_HEALTH_UNKNOWN),
                }
                if temperature is None:
                    missing_names.append(physical_name)
            fallback_values = self._read_unassigned_disk_temperatures()
            if len(fallback_values) == len(missing_names):
                for physical_name, temperature in zip(missing_names, fallback_values):
                    disk_sensors_by_name[physical_name]["temperature_c"] = temperature
            for device in devices:
                disk_sensors = [
                    disk_sensors_by_name[physical_name]
                    for physical_name in self._linux_backing_disks(device)
                    if physical_name in disk_sensors_by_name
                ]
                if not disk_sensors:
                    continue
                temperatures[os.path.normcase(device)] = {
                    "name": disk_sensors[0]["name"],
                    "temperature_c": disk_sensors[0]["temperature_c"],
                    "health": disk_sensors[0].get("health", DISK_HEALTH_UNKNOWN),
                    "physical_disks": disk_sensors,
                }
            temperatures["__physical_disks__"] = list(disk_sensors_by_name.values())
        else:
            temperatures = {}
        self.disk_temperature_cache = temperatures
        self.disk_temperature_time = now
        return temperatures

    @staticmethod
    def _mountpoint_rank(partition):
        """完整匹配 NAS 卷根路径，优先选择数字较小的 /volumeN 挂载点。"""
        mountpoint = str(getattr(partition, "mountpoint", "") or "")
        match = re.fullmatch(r"/volume(\d+)/?", mountpoint)
        return (0, int(match.group(1))) if match else (1, 0)

    def _disk_details(self):
        """采集所有有效本地磁盘分区的容量、占用率和温度。"""
        selected_partitions = {}
        for partition in psutil.disk_partitions(all=False):
            options = set(str(partition.opts).lower().split(","))
            if "cdrom" in options:
                continue
            device = str(partition.device or partition.mountpoint)
            device_key = os.path.normcase(device)
            current = selected_partitions.get(device_key)
            # 完整匹配避免 overlay 子目录冒充卷根；同优先级保留首项与设备顺序。
            if current is None or self._mountpoint_rank(partition) < self._mountpoint_rank(current[0]):
                selected_partitions[device_key] = (partition, device)
        partitions = []
        # 先选定每个设备的代表挂载点，淘汰的重复路径不触发容量查询。
        for device_key, (partition, device) in selected_partitions.items():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            if usage.total <= 0:
                continue
            partitions.append((partition, usage, device, device_key))
        if not partitions:
            mountpoint = os.path.abspath(os.sep)
            usage = psutil.disk_usage(mountpoint)
            fallback = type("DiskPartition", (), {"device": mountpoint, "mountpoint": mountpoint, "fstype": ""})()
            partitions.append((fallback, usage, mountpoint, os.path.normcase(mountpoint)))
        temperatures = self._disk_temperatures([item[2] for item in partitions])
        grouped = {}
        for partition, usage, device, device_key in partitions:
            sensor = temperatures.get(device_key, {})
            if platform.system() == "Windows" and not sensor:
                device_number = self._windows_device_number(device)
                if device_number is not None:
                    sensor = {"name": "DISK" + str(device_number), "temperature_c": None, "health": DISK_HEALTH_UNKNOWN}
            disk_sensors = sensor.get("physical_disks") or [sensor]
            if platform.system() == "Linux":
                block_name = self._linux_block_device_name(device)
                is_logical_volume = (
                    os.path.dirname(device) == "/dev/mapper"
                    or re.fullmatch(r"(?:dm-|md)\d+", block_name)
                    or len(disk_sensors) > 1
                )
                if is_logical_volume:
                    # 一个卷只记录一份文件系统容量，不能向每块 RAID 成员盘重复分配。
                    # 同一组物理盘上的不同逻辑卷也必须各自保留挂载点与占用率。
                    disk_sensors = [{
                        "name": block_name or device,
                        "temperature_c": max(
                            (item["temperature_c"] for item in disk_sensors if item.get("temperature_c") is not None),
                            default=None,
                        ),
                        "health": max((item.get("health", DISK_HEALTH_UNKNOWN) for item in disk_sensors),
                                      default=DISK_HEALTH_UNKNOWN),
                    }]
                elif not sensor:
                    # 容量来自可读挂载点，温度或 SMART 缺失不应使容量一起丢失。
                    disk_sensors = [{"name": self._linux_physical_disk(device) or device}]
            for disk_sensor in disk_sensors:
                name = disk_sensor.get("name") or device
                current = grouped.get(name)
                if current is None:
                    current = {
                        "name": name,
                        "devices": [],
                        "mountpoints": [],
                        "filesystems": [],
                        "used_bytes": 0,
                        "total_bytes": 0,
                        "temperature_c": disk_sensor.get("temperature_c"),
                        "health": disk_sensor.get("health", DISK_HEALTH_UNKNOWN),
                    }
                    grouped[name] = current
                current["devices"].append(device)
                current["mountpoints"].append(str(partition.mountpoint))
                filesystem = str(partition.fstype or "")
                if filesystem and filesystem not in current["filesystems"]:
                    current["filesystems"].append(filesystem)
                current["used_bytes"] += int(usage.used)
                current["total_bytes"] += int(usage.total)
                if current["temperature_c"] is None:
                    current["temperature_c"] = disk_sensor.get("temperature_c")
                current["health"] = max(current["health"], disk_sensor.get("health", DISK_HEALTH_UNKNOWN))
        details = []
        for current in grouped.values():
            # 标签仅用于显示和样式筛选；设备名仍用于 I/O 关联与多任务快照合并。
            current["label"] = self._disk_label(current)
            total_bytes = current["total_bytes"]
            current["percent"] = round(current["used_bytes"] * 100 / total_bytes, 1) if total_bytes else 0
            details.append(current)
        mounted_names = {item["name"] for item in details}
        for sensor in temperatures.get("__physical_disks__", ()):
            if sensor["name"] in mounted_names:
                continue
            # SMART 可能使用 /dev/nvme1 控制器路径，容量必须按 nvme1n1 命名空间读取。
            total_bytes = self._read_linux_disk_capacity(sensor["name"]) if platform.system() == "Linux" else 0
            details.append({
                "name": sensor["name"],
                "label": sensor["name"],
                "devices": [sensor["device"]],
                "mountpoints": [],
                "filesystems": [],
                "used_bytes": 0,
                "total_bytes": total_bytes,
                # 未挂载不代表空盘；文件系统已用与剩余空间无法由设备大小推断。
                "free_bytes": 0,
                "percent": 0,
                "temperature_c": sensor["temperature_c"],
                "health": sensor.get("health", DISK_HEALTH_UNKNOWN),
            })
        return details

    @staticmethod
    def _disk_usage(disks=None):
        """汇总已挂载文件系统用量，排除裸盘及 LVM/RAID 成员盘的设备容量。"""
        if disks is not None:
            # 缺少挂载点字段的旧调用方仍按原有方式累计；明确无挂载点的仅供明细展示。
            mounted_disks = [item for item in disks if item.get("mountpoints") or "mountpoints" not in item]
            total_bytes = sum(item["total_bytes"] for item in mounted_disks)
            used_bytes = sum(item["used_bytes"] for item in mounted_disks)
            percent = used_bytes * 100 / total_bytes if total_bytes else 0
            return used_bytes, total_bytes, round(percent, 1)
        total_bytes = 0
        used_bytes = 0
        visited_devices = set()
        for partition in psutil.disk_partitions(all=False):
            options = set(str(partition.opts).lower().split(","))
            if "cdrom" in options:
                continue
            device_key = os.path.normcase(partition.device or partition.mountpoint)
            if device_key in visited_devices:
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            if usage.total <= 0:
                continue
            visited_devices.add(device_key)
            total_bytes += int(usage.total)
            used_bytes += int(usage.used)
        if total_bytes <= 0:
            usage = psutil.disk_usage(os.path.abspath(os.sep))
            total_bytes, used_bytes = int(usage.total), int(usage.used)
        percent = used_bytes * 100 / total_bytes if total_bytes else 0
        return used_bytes, total_bytes, round(percent, 1)
