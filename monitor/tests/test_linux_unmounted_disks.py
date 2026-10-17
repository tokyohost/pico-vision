"""验证 issue #3：未挂载物理盘应显示设备容量，且不影响文件系统汇总。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from collectTask.tasks.disk_capacity_health import DiskCapacityHealthTask
from monitor_core.collectors import disk as disk_module
from monitor_core.collectors.disk import DiskMetricsMixin


class LinuxUnmountedDiskTests(unittest.TestCase):
    """覆盖裸盘、NVMe 控制器路径、读盘失败和 LVM 容量去重。"""

    def setUp(self):
        """隔离 sysfs 和挂载列表，保留真实磁盘发现与快照发布路径。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.block_root = Path(temporary.name)
        self.enterContext(mock.patch.object(disk_module, "Path", side_effect=self._path))
        self.enterContext(mock.patch.object(disk_module.platform, "system", return_value="Linux"))
        self.enterContext(mock.patch.object(disk_module.psutil, "disk_partitions", return_value=[
            SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4", opts="rw"),
        ]))
        self.enterContext(mock.patch.object(disk_module.psutil, "disk_usage",
                                          return_value=SimpleNamespace(total=1000, used=400)))
        self.enterContext(mock.patch.object(disk_module.subprocess, "run", side_effect=FileNotFoundError))
        self.enterContext(mock.patch.object(DiskMetricsMixin, "_read_linux_disk_temperature", return_value=None))
        self.enterContext(mock.patch.object(DiskMetricsMixin, "_read_unassigned_disk_temperatures", return_value=[]))
        self.collector = DiskMetricsMixin()
        self.collector.disk_temperature_time = 0.0
        self.collector.disk_temperature_cache = {}
        self._block("sda", 100)

    def _path(self, value):
        """仅替换 Linux 块设备 sysfs 根目录。"""
        return self.block_root if str(value) == "/sys/class/block" else Path(value)

    def _block(self, name, sectors):
        """创建以 512 字节扇区计数的块设备容量输入。"""
        root = self.block_root / name
        root.mkdir()
        (root / "size").write_text(str(sectors), encoding="ascii")
        return root

    def test_unmounted_disks_publish_capacity_without_smart_or_device_nodes(self):
        """确认 SATA、NVMe 和 eMMC 裸盘仅凭 sysfs 即可发布真实设备容量。"""
        for name in ("sdb", "nvme1n1", "mmcblk0"):
            self._block(name, 8388608)
        disks = self.collector._disk_details()
        physical = {disk["name"]: disk for disk in self.collector._physical_disk_statistics(disks)}
        for disk in disks:
            if disk["name"] == "sda":
                continue
            with self.subTest(name=disk["name"]):
                self.assertEqual(disk["total_bytes"], 4294967296)
                self.assertEqual(physical[disk["name"]]["total_bytes"], 4294967296)
                self.assertEqual((disk["used_bytes"], disk["free_bytes"], disk["percent"]), (0, 0, 0))
                self.assertEqual(disk["mountpoints"], [])
                self.assertEqual(disk["health"], 0)
        self.assertEqual(set(physical), {"sda", "sdb", "nvme1n1", "mmcblk0"})

    def test_sysfs_capacity_uses_512_bytes_even_for_4k_sector_devices(self):
        """确认 4Kn 设备的 sysfs size 仍以 512 字节为单位，避免容量放大八倍。"""
        root = self._block("nvme1n1", 8388608)
        (root / "queue").mkdir()
        (root / "queue" / "logical_block_size").write_text("4096", encoding="ascii")
        disk = next(item for item in self.collector._disk_details() if item["name"] == "nvme1n1")
        self.assertEqual(disk["total_bytes"], 4294967296)

    def test_controller_path_reads_capacity_from_namespace(self):
        """确认 SMART 只返回控制器路径时，容量读取仍使用完整 NVMe 命名空间。"""
        self._block("nvme1n2", 4096)
        sensors = {"__physical_disks__": [
            {"name": "nvme1n2", "device": "/dev/nvme1", "temperature_c": 38.0, "health": 1},
        ]}
        with mock.patch.object(self.collector, "_disk_temperatures", return_value=sensors):
            disk = self.collector._disk_details()[-1]
        self.assertEqual(disk["total_bytes"], 2097152)
        self.assertEqual(disk["devices"], ["/dev/nvme1"])
        self.assertEqual((disk["temperature_c"], disk["health"]), (38.0, 1))

    def test_unmounted_capacity_does_not_dilute_mounted_usage(self):
        """确认新加入的裸盘容量不改变已挂载文件系统的总容量和占用率。"""
        self._block("nvme1n1", 8388608)
        disks = self.collector._disk_details()
        mounted = next(item for item in disks if item["mountpoints"])
        self.assertEqual((mounted["total_bytes"], mounted["used_bytes"], mounted["percent"]), (1000, 400, 40.0))
        self.assertEqual(self.collector._disk_usage(disks), (400, 1000, 40.0))
        self.assertEqual(self.collector._disk_usage([disks[-1]]), (0, 0, 0))

    def test_capacity_task_publishes_unmounted_device_and_preserves_overview(self):
        """确认容量任务合并后的两类快照都有设备容量，总览仍只统计已挂载卷。"""
        self._block("nvme1n1", 8388608)
        snapshot = DiskCapacityHealthTask(self.collector).collect()
        for key in ("disks", "physical_disks"):
            disk = next(item for item in snapshot[key] if item["name"] == "nvme1n1")
            self.assertEqual(disk["total_bytes"], 4294967296)
            self.assertEqual(disk["free_bytes"], 0)
        self.assertEqual(snapshot["disk"], {"used_bytes": 400, "total_bytes": 1000, "percent": 40.0})

    def test_invalid_or_missing_size_retains_sensor_without_failing_collection(self):
        """确认热拔出、异常容量、负数和无法读取时仅回退该磁盘容量。"""
        root = self._block("nvme1n1", 0)
        sensors = {"__physical_disks__": [
            {"name": "nvme1n1", "device": "/dev/nvme1", "temperature_c": 38.0, "health": 1},
        ]}
        for size in ("0", "-1", "invalid", None):
            with self.subTest(size=size):
                if size is None:
                    (root / "size").unlink()
                else:
                    (root / "size").write_text(size, encoding="ascii")
                with mock.patch.object(self.collector, "_disk_temperatures", return_value=sensors):
                    disks = self.collector._disk_details()
                self.assertEqual(disks[-1]["total_bytes"], 0)
                self.assertEqual((disks[-1]["temperature_c"], disks[-1]["health"]), (38.0, 1))
                self.assertEqual(self.collector._disk_usage(disks), (400, 1000, 40.0))
        with mock.patch.object(self.collector, "_disk_temperatures", return_value=sensors), \
                mock.patch.object(Path, "read_text", side_effect=PermissionError):
            disks = self.collector._disk_details()
        self.assertEqual(disks[-1]["total_bytes"], 0)
        self.assertEqual((disks[-1]["temperature_c"], disks[-1]["health"]), (38.0, 1))

    def test_mount_transition_replaces_device_capacity_with_filesystem_usage(self):
        """确认磁盘挂载后切换为文件系统统计，卸载后恢复设备容量。"""
        self._block("nvme1n1", 8388608)
        partitions = [SimpleNamespace(device="/dev/nvme1n1p1", mountpoint="/data", fstype="ext4", opts="rw")]
        with mock.patch.object(disk_module.psutil, "disk_partitions", return_value=partitions):
            mounted = next(item for item in self.collector._disk_details() if item["name"] == "nvme1n1")
        self.assertEqual((mounted["total_bytes"], mounted["used_bytes"], mounted["percent"]), (1000, 400, 40.0))
        unmounted = next(item for item in self.collector._disk_details() if item["name"] == "nvme1n1")
        self.assertEqual((unmounted["total_bytes"], unmounted["used_bytes"], unmounted["percent"]), (4294967296, 0, 0))


if __name__ == "__main__":
    unittest.main()
