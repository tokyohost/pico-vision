"""复现 issue #1：LVM 卷缺少设备别名或 SMART 数据时仍应显示容量。"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from monitor_core.collectors import disk as disk_module
from monitor_core.collectors.disk import DiskMetricsMixin


class LinuxLvmDiskTests(unittest.TestCase):
    """验证缺失 udev 别名、叠加 RAID 和多逻辑卷的容量关联。"""

    def setUp(self):
        """建立临时 sysfs，避免测试依赖宿主机磁盘。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.block_root = Path(temporary.name)
        self.enterContext(mock.patch.object(disk_module, "Path", side_effect=self._path))
        self.enterContext(mock.patch.object(disk_module.platform, "system", return_value="Linux"))
        self.collector = DiskMetricsMixin()
        self.collector.disk_temperature_cache = {}
        self.collector.disk_temperature_time = 0.0

    def _path(self, value):
        """仅将 sysfs 根目录重定向到本用例的隔离目录。"""
        return self.block_root if str(value) == "/sys/class/block" else Path(value)

    def _block(self, name, slaves=(), mapper_name=None):
        """生成内核块设备和逻辑卷名称，不创建任何 /dev 别名。"""
        root = self.block_root / name
        (root / "slaves").mkdir(parents=True)
        (root / "size").write_text("2048", encoding="ascii")
        for slave in slaves:
            (root / "slaves" / slave).mkdir()
        if mapper_name:
            (root / "dm").mkdir()
            (root / "dm" / "name").write_text(mapper_name + "\n", encoding="ascii")

    def _details(self, partitions, sensors):
        """使用真实容量汇总路径并替换系统挂载与传感器输入。"""
        with mock.patch.object(disk_module.psutil, "disk_partitions", return_value=partitions), \
                mock.patch.object(disk_module.psutil, "disk_usage", side_effect=lambda path: {
                    "/volume1": SimpleNamespace(total=1000, used=400),
                    "/volume2": SimpleNamespace(total=2000, used=500),
                }[path]), \
                mock.patch.object(self.collector, "_disk_temperatures", return_value=sensors):
            return self.collector._disk_details()

    @staticmethod
    def _partition(device, mountpoint):
        """构造 psutil 本地文件系统挂载条目。"""
        return SimpleNamespace(device=device, mountpoint=mountpoint, opts="rw", fstype="ext4")

    def test_missing_mapper_alias_resolves_lvm_over_raid(self):
        """确认没有 /dev/mapper 链接也能沿 dm → md → SATA 分区回溯。"""
        self._block("dm-0", ("md1",), "nas--vg-volume1")
        self._block("md1", ("sda1", "sdb1"))
        self._block("sda")
        self._block("sdb")
        self.assertEqual(self.collector._linux_backing_disks("/dev/mapper/nas--vg-volume1"), ("sda", "sdb"))

    def test_mounted_volume_survives_missing_smart_and_sysfs(self):
        """确认没有传感器和块设备映射时仍保留可读挂载点容量。"""
        disks = self._details([self._partition("/dev/mapper/unknown-volume1", "/volume1")], {})
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["mountpoints"], ["/volume1"])
        self.assertEqual((disks[0]["used_bytes"], disks[0]["total_bytes"], disks[0]["percent"]), (400, 1000, 40.0))
        self.assertIsNone(disks[0]["temperature_c"])
        self.assertEqual(disks[0]["health"], 0)

    def test_each_lvm_volume_retains_its_capacity_without_raid_double_count(self):
        """确认共享 RAID 的两个逻辑卷分别显示容量，总览只累计一次。"""
        physical = [
            {"name": name, "device": "/dev/" + name, "temperature_c": temperature, "health": 1}
            for name, temperature in (("sda", 38.0), ("sdb", 40.0))
        ]
        partitions = []
        sensors = {"__physical_disks__": physical}
        for index in (1, 2):
            self._block("dm-" + str(index - 1), ("md1",), "nas-volume" + str(index))
            device = "/dev/mapper/nas-volume" + str(index)
            partitions.append(self._partition(device, "/volume" + str(index)))
            sensors[os.path.normcase(device)] = {"name": "sda", "physical_disks": physical}
        disks = self._details(partitions, sensors)
        mounted = [disk for disk in disks if disk["mountpoints"]]
        self.assertEqual(len(mounted), 2)
        self.assertEqual([(disk["mountpoints"], disk["total_bytes"], disk["percent"]) for disk in mounted],
                         [(["/volume1"], 1000, 40.0), (["/volume2"], 2000, 25.0)])
        self.assertEqual(self.collector._disk_usage(disks), (900, 3000, 30.0))
        self.assertEqual({disk["name"] for disk in disks if not disk["mountpoints"]}, {"sda", "sdb"})

    def test_direct_dm_device_and_duplicate_mount_are_not_counted_twice(self):
        """确认直接使用 dm 设备时保留容量，并跳过同设备重复挂载。"""
        self._block("dm-0", ("sda",), "nas-volume1")
        self._block("sda")
        partitions = [self._partition("/dev/dm-0", "/volume1"), self._partition("/dev/dm-0", "/duplicate")]
        disks = self._details(partitions, {})
        self.assertEqual(self.collector._disk_usage(disks), (400, 1000, 40.0))
        self.assertEqual(disks[0]["mountpoints"], ["/volume1"])


if __name__ == "__main__":
    unittest.main()
