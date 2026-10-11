"""复现 issue #2：NVMe 控制器和命名空间不得生成重复或截断的磁盘。"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from monitor_core.collectors import disk as disk_module
from monitor_core.collectors.disk import DiskMetricsMixin


class LinuxNvmeDiskTests(unittest.TestCase):
    """验证 NVMe 规范化、扫描去重、多命名空间和 SMART 有效值回退。"""

    def setUp(self):
        """隔离 sysfs 输入，使两种扫描顺序可重复验证。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.block_root = Path(temporary.name)
        self.enterContext(mock.patch.object(disk_module, "Path", side_effect=self._path))
        self.enterContext(mock.patch.object(disk_module.platform, "system", return_value="Linux"))

    def _path(self, value):
        """将 Linux 块设备 sysfs 重定向到测试目录。"""
        return self.block_root if str(value) == "/sys/class/block" else Path(value)

    def _namespace(self, name):
        """创建一个有容量且没有分区标记的真实块设备输入。"""
        root = self.block_root / name
        root.mkdir()
        (root / "size").write_text("2048", encoding="ascii")

    def _scan(self, paths):
        """替换 smartctl 扫描结果，保留实际发现与归一化逻辑。"""
        payload = {"devices": [{"name": path, "type": "nvme"} for path in paths]}
        with mock.patch.object(disk_module.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(payload))):
            return DiskMetricsMixin._discover_linux_disks()

    def test_bare_namespaces_and_partitions_keep_the_complete_disk_name(self):
        """确认裸 NVMe、eMMC 和带分区后缀的名称都不会被截断。"""
        for device, expected in (("nvme0n1", "nvme0n1"), ("nvme10n22", "nvme10n22"),
                                 ("nvme0n1p2", "nvme0n1"), ("mmcblk0", "mmcblk0"),
                                 ("mmcblk0p2", "mmcblk0"), ("sda2", "sda"), ("dm-0", "dm-0")):
            with self.subTest(device=device):
                self.assertEqual(DiskMetricsMixin._linux_physical_disk("/dev/" + device), expected)

    def test_controller_and_namespace_are_deduplicated_in_either_scan_order(self):
        """确认四块 NVMe 扫描顺序变化时仍只生成四条命名空间记录。"""
        paths = []
        for index in range(4):
            name = "nvme" + str(index) + "n1"
            self._namespace(name)
            paths.extend(["/dev/nvme" + str(index), "/dev/" + name])
        for order in (paths, paths[::-1]):
            with self.subTest(order=order):
                descriptors = self._scan(order)
                self.assertEqual(descriptors, [("nvme" + str(index) + "n1", "/dev/nvme" + str(index) + "n1", "nvme")
                                               for index in range(4)])

    def test_controller_uses_actual_namespaces_without_inventing_namespace_one(self):
        """确认只有第二命名空间时不会凭空增加 n1，多命名空间也不会合并。"""
        self._namespace("nvme0n2")
        self._namespace("nvme10n1")
        self._namespace("nvme10n2")
        descriptors = self._scan(["/dev/nvme0", "/dev/nvme10", "/dev/nvme10n2"])
        self.assertEqual({item[0] for item in descriptors}, {"nvme0n2", "nvme10n1", "nvme10n2"})

    def test_unknown_namespace_health_falls_back_to_valid_controller_health(self):
        """确认同一 NVMe 的有效 SMART 状态不会被命名空间未知状态覆盖。"""
        collector = DiskMetricsMixin()
        with mock.patch.object(collector, "_read_smart_health", side_effect=lambda path, kind: {
            "/dev/nvme0n1": 0, "/dev/nvme0": 1,
        }[path]):
            health = collector._disk_health([("nvme0n1", "/dev/nvme0n1", "nvme")])
        self.assertEqual(health, {"nvme0n1": 1})

    def test_valid_namespace_health_is_retained(self):
        """确认命名空间已有健康告警时保留状态，避免控制器回退掩盖故障。"""
        collector = DiskMetricsMixin()
        with mock.patch.object(collector, "_read_smart_health", return_value=5) as reader:
            self.assertEqual(collector._disk_health([("nvme0n1", "/dev/nvme0n1", "nvme")]), {"nvme0n1": 5})
        reader.assert_called_once_with("/dev/nvme0n1", "nvme")


if __name__ == "__main__":
    unittest.main()
