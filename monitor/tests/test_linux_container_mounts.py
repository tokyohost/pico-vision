"""复现 issue #5：容器重复挂载不得替换 NAS 存储卷的代表挂载点。"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from monitor_core.collectors import disk as disk_module
from monitor_core.collectors.disk import DiskMetricsMixin


class LinuxContainerMountTests(unittest.TestCase):
    """验证卷根路径优先、设备去重和容量查询次数。"""

    def setUp(self):
        """隔离系统类型、块设备映射和传感器，保留真实挂载筛选与容量汇总。"""
        self.collector = DiskMetricsMixin()
        self.enterContext(mock.patch.object(disk_module.platform, "system", return_value="Linux"))
        self.enterContext(mock.patch.object(
            self.collector, "_linux_block_device_name", side_effect=lambda device: os.path.basename(device)
        ))
        self.enterContext(mock.patch.object(self.collector, "_disk_temperatures", return_value={}))

    @staticmethod
    def _partition(device, mountpoint, opts="rw"):
        """构造容器中由 psutil 枚举的文件系统挂载条目。"""
        return SimpleNamespace(device=device, mountpoint=mountpoint, opts=opts, fstype="ext4")

    def _details(self, partitions, usages):
        """仅允许读取预期挂载点，意外查询重复路径时立即使测试失败。"""
        def disk_usage(path):
            """返回指定容量或模拟权限异常，拒绝查询未胜出的挂载点。"""
            value = usages[path]
            if isinstance(value, Exception):
                raise value
            return SimpleNamespace(total=value[0], used=value[1])

        with mock.patch.object(disk_module.psutil, "disk_partitions", return_value=partitions), \
                mock.patch.object(disk_module.psutil, "disk_usage", side_effect=disk_usage) as reader:
            details = self.collector._disk_details()
        return details, reader

    def test_seven_volumes_survive_bind_mounts_in_either_enumeration_order(self):
        """确认七个逻辑卷保留真实卷号，重复挂载不查询容量且不重复累计。"""
        partitions = []
        usages = {}
        for volume, number in enumerate((4, 0, 1, 2, 3, 6, 5), start=1):
            device = "/dev/dm-" + str(number)
            mountpoint = "/volume" + str(volume)
            paths = [
                "/data", "/etc/resolv.conf", "/etc/hostname", "/etc/hosts",
                "/var/lib/pico-monitor", "/volume3/@docker/overlay2/abc/merged" + mountpoint,
                mountpoint,
            ]
            partitions.extend(self._partition(device, path) for path in paths)
            usages[mountpoint] = (volume * 1000, volume * 100)
        for order in (partitions, partitions[::-1]):
            with self.subTest(reversed_order=order is not partitions):
                details, reader = self._details(order, usages)
                statistics = self.collector._physical_disk_statistics(details)
                self.assertEqual(len(statistics), 7)
                self.assertEqual(
                    {item["mountpoints"][0] for item in statistics}, set(usages)
                )
                self.assertTrue(all(len(item["mountpoints"]) == 1 for item in statistics))
                self.assertEqual(self.collector._disk_usage(details), (2800, 28000, 10.0))
                self.assertCountEqual(reader.call_args_list, [mock.call(path) for path in usages])

    def test_same_device_prefers_numeric_volume_order_and_accepts_trailing_slash(self):
        """确认同设备的卷号按数值选择，并允许卷根末尾的一个斜杠。"""
        for paths in (("/volume10", "/volume2/"), ("/volume2/", "/volume10")):
            with self.subTest(paths=paths):
                partitions = [self._partition("/dev/dm-0", path) for path in paths]
                details, reader = self._details(partitions, {"/volume2/": (2000, 500)})
                self.assertEqual(details[0]["mountpoints"], ["/volume2/"])
                reader.assert_called_once_with("/volume2/")

    def test_nested_volume_paths_do_not_receive_volume_root_priority(self):
        """确认 overlay、子目录和相似名称不能通过前缀匹配冒充存储卷根。"""
        for path in (
            "/volume3/@docker/overlay2/abc/merged/volume6", "/volume3/subdir",
            "/volume3abc", "/volume3//", "/volume", "/Volume3", "/volume3\n",
        ):
            with self.subTest(path=path):
                partitions = [self._partition("/dev/dm-0", item) for item in ("/data", path)]
                details, reader = self._details(partitions, {"/data": (1000, 400)})
                self.assertEqual(details[0]["mountpoints"], ["/data"])
                reader.assert_called_once_with("/data")

    def test_non_volume_mounts_keep_the_first_path_and_device_order(self):
        """确认普通挂载保持原有顺序，后续重复路径不再查询容量。"""
        partitions = [
            self._partition("/dev/dm-1", "/data"),
            self._partition("/dev/dm-0", "/backup"),
            self._partition("/dev/dm-1", "/etc/hosts"),
        ]
        details, reader = self._details(partitions, {"/data": (1000, 400), "/backup": (2000, 500)})
        self.assertEqual([item["mountpoints"] for item in details], [["/data"], ["/backup"]])
        self.assertEqual(reader.call_args_list, [mock.call("/data"), mock.call("/backup")])

    def test_unreadable_or_empty_winner_does_not_query_duplicate_mounts(self):
        """确认选中路径异常或容量无效时跳过该设备，不查询已淘汰的重复挂载。"""
        for unavailable in (PermissionError("测试权限不足"), OSError("测试挂载失效"), (0, 0)):
            with self.subTest(unavailable=unavailable):
                partitions = [
                    self._partition("/dev/dm-0", "/data"),
                    self._partition("/dev/dm-0", "/volume3"),
                    self._partition("/dev/dm-1", "/volume4"),
                ]
                details, reader = self._details(partitions, {
                    "/volume3": unavailable, "/volume4": (1000, 400),
                })
                self.assertEqual([item["mountpoints"] for item in details], [["/volume4"]])
                self.assertEqual(reader.call_args_list, [mock.call("/volume3"), mock.call("/volume4")])

    def test_cdrom_is_filtered_before_selecting_representative_mount(self):
        """确认只读光盘条目不会凭卷根路径抢占同设备的普通挂载。"""
        partitions = [
            self._partition("/dev/dm-0", "/volume1", "ro,cdrom"),
            self._partition("/dev/dm-0", "/data"),
        ]
        details, reader = self._details(partitions, {"/data": (1000, 400)})
        self.assertEqual(details[0]["mountpoints"], ["/data"])
        reader.assert_called_once_with("/data")

    def test_no_valid_mounts_preserve_root_capacity_fallback(self):
        """确认胜出路径不可读且没有其它设备时，仍通过根目录兜底。"""
        partitions = [self._partition("/dev/dm-0", path) for path in ("/data", "/volume3")]
        root = os.path.abspath(os.sep)
        details, reader = self._details(partitions, {
            "/volume3": PermissionError("测试权限不足"), root: (1000, 400),
        })
        self.assertEqual(details[0]["mountpoints"], [root])
        self.assertEqual(reader.call_args_list, [mock.call("/volume3"), mock.call(root)])


if __name__ == "__main__":
    unittest.main()
