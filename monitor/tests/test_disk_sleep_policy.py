"""验证 Linux 磁盘休眠保护、SMART 周期和设置兼容性。"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from monitor_core.arguments import create_argument_parser
from monitor_core.config import parse_disk_smart_interval, validate_disk_settings
from monitor_core.collectors.disk import DiskMetricsMixin
from monitor_core.collectors import disk_policy
from desktop.common.settings import DEFAULT_SETTINGS, TraySettingsStore, apply_worker_arguments
from monitor_core.collectors.cpu import CpuMetricsMixin
from monitor_core.service import MonitorService
from desktop.linux.bridge import LinuxInvokeBridge


class DiskSleepPolicyTests(unittest.TestCase):
    """用内核计数器和命令替身验证保护边界，不访问真实磁盘。"""

    def setUp(self):
        """创建受保护采集器及可控的时间、分区和 I/O 输入。"""
        self.enterContext(mock.patch.object(disk_policy.platform, "system", return_value="Linux"))
        self.collector = DiskMetricsMixin()
        self.collector.configure_disk_policy(False, 30)
        self.names = self.enterContext(mock.patch.object(self.collector, "_list_linux_physical_disks", return_value=("sda",)))
        self.enterContext(mock.patch.object(self.collector, "_linux_backing_disks", return_value=("sda",)))
        self.enterContext(mock.patch.object(self.collector, "_read_linux_disk_capacity", return_value=1000))
        self.clock = self.enterContext(mock.patch.object(disk_policy.time, "monotonic", return_value=100.0))
        self.counters = self.enterContext(mock.patch.object(disk_policy.psutil, "disk_io_counters", return_value={"sda": SimpleNamespace(read_bytes=100, write_bytes=0)}))
        self.partitions = self.enterContext(mock.patch.object(disk_policy.psutil, "disk_partitions", return_value=[
            SimpleNamespace(device="/dev/sda1", mountpoint="/volume1", fstype="ext4", opts="rw")]))
        self.usage = self.enterContext(mock.patch.object(disk_policy.psutil, "disk_usage", return_value=SimpleNamespace(used=100, total=1000, free=900, percent=10)))
        self.kind = self.enterContext(mock.patch.object(self.collector, "_safe_ata_type", return_value="sat"))
        self.command = self.enterContext(mock.patch.object(disk_policy.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"temperature": {"current": 32}, "smart_status": {"passed": True}}))))

    def advance(self, seconds=31, read_bytes=200):
        """模拟业务读取及时间推进，避免测试依赖墙钟等待。"""
        self.clock.return_value += seconds
        self.counters.return_value = {"sda": SimpleNamespace(read_bytes=read_bytes, write_bytes=0)}

    def test_idle_and_first_sample_never_query_disk(self):
        """首次与持续空闲只读内核信息，不触发扫描、SMART 或 statvfs。"""
        self.collector._passive_disk_details()
        self.clock.return_value += 1801
        result = self.collector._passive_disk_details()
        self.command.assert_not_called()
        self.usage.assert_not_called()
        self.assertIsNone(result[0]["temperature_c"])
        self.assertEqual(result[0]["health"], 0)
        self.assertTrue(result[0]["capacity_stale"])

    def test_activity_uses_guarded_query_and_preserves_capacity_on_idle(self):
        """业务唤醒后安全采集，空闲后沿用容量并显式标记过期。"""
        self.collector._passive_disk_details()
        self.advance()
        result = self.collector._passive_disk_details()
        command = self.command.call_args.args[0]
        self.assertEqual(command[:6], ["smartctl", "-n", "standby,3,5", "-d", "sat", "-j"])
        self.assertIn("-a", command)
        self.assertFalse(result[0]["capacity_stale"])
        self.assertEqual(result[0]["health"], 1)
        self.command.reset_mock()
        self.usage.reset_mock()
        result = self.collector._passive_disk_details()
        self.command.assert_not_called()
        self.usage.assert_not_called()
        self.assertEqual(result[0]["used_bytes"], 100)
        self.assertTrue(result[0]["capacity_stale"])
        self.assertIsNotNone(result[0]["capacity_updated_at"])

    def test_sleep_unknown_and_unsupported_do_not_fall_back(self):
        """休眠、失败或不支持电源检测均不更新成功时间，也不回退查询。"""
        for code in (1, 2, 3, 5):
            with self.subTest(code=code):
                self.collector._protected_io_by_task = {}
                self.collector._protected_attempts_by_task = {}
                self.collector._passive_disk_details()
                self.advance(read_bytes=self.counters.return_value["sda"].read_bytes + 100)
                self.command.return_value.returncode = code
                self.command.reset_mock()
                self.collector._passive_disk_details()
                self.assertEqual(self.command.call_count, 1)
                self.assertEqual(self.collector._protected_health_times, {})
                self.usage.assert_not_called()

    def test_usb_raid_and_unknown_types_are_passive(self):
        """未知桥接或控制器路径没有主动探测兜底。"""
        self.kind.return_value = None
        self.collector._passive_disk_details()
        self.advance()
        self.collector._passive_disk_details()
        self.command.assert_not_called()
        self.usage.assert_not_called()

    def test_temperature_does_not_refresh_capacity(self):
        """温度任务即使观测到活动也不读取文件系统容量。"""
        self.collector._passive_disk_details(collect_capacity=False)
        self.advance()
        self.collector._passive_disk_details(collect_capacity=False)
        self.command.assert_called_once()
        self.usage.assert_not_called()

    def test_smart_period_and_hot_update_preserve_success_time(self):
        """温度可刷新属性，但健康仅在分钟周期到期后刷新。"""
        self.collector._passive_disk_details()
        self.advance()
        self.collector._passive_disk_details()
        stamp = self.collector._protected_health_times["sda"]
        self.advance(read_bytes=300)
        self.collector._passive_disk_details()
        self.assertIn("-A", self.command.call_args.args[0])
        self.assertNotIn("-a", self.command.call_args.args[0])
        self.collector.configure_disk_policy(False, 1)
        self.assertEqual(self.collector._protected_health_times["sda"], stamp)
        self.advance(read_bytes=400)
        self.collector._passive_disk_details()
        self.assertIn("-a", self.command.call_args.args[0])
        self.collector.configure_disk_policy(False, 60)
        self.advance(read_bytes=500)
        self.collector._passive_disk_details()
        self.assertIn("-A", self.command.call_args.args[0])

    def test_failed_query_is_rate_limited(self):
        """失败后即便业务连续读写也至少间隔三十秒重试。"""
        self.collector._passive_disk_details()
        self.command.return_value.returncode = 5
        self.advance()
        self.collector._passive_disk_details()
        self.advance(seconds=1, read_bytes=300)
        self.collector._passive_disk_details()
        self.command.assert_called_once()

    def test_failed_query_backoff_is_shared_between_tasks(self):
        """温度任务失败后，容量任务不能在同一秒再次查询相同磁盘。"""
        self.collector._passive_disk_details()
        self.collector._passive_disk_details(collect_capacity=False)
        self.command.return_value.returncode = 5
        self.advance()
        self.collector._passive_disk_details(collect_capacity=False)
        self.collector._passive_disk_details()
        self.command.assert_called_once()
        self.usage.assert_not_called()

    def test_defaults_validation_and_worker_round_trip(self):
        """默认兼容旧行为，命令行覆盖和整数校验保持一致。"""
        args = create_argument_parser().parse_args([])
        self.assertTrue(args.disk_allow_wakeup)
        self.assertEqual(args.disk_smart_interval_minutes, 30)
        for value in (True, False, 0, -1, 1.5, "1.0", "bad", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_disk_smart_interval(value)
        self.assertEqual(parse_disk_smart_interval("60"), 60)
        with self.assertRaises(ValueError):
            validate_disk_settings({"disk_allow_wakeup": "false"})
        settings = dict(DEFAULT_SETTINGS, disk_allow_wakeup=False, disk_smart_interval_minutes=7)
        arguments = apply_worker_arguments([], settings)
        args = create_argument_parser().parse_args(arguments)
        self.assertFalse(args.disk_allow_wakeup)
        self.assertEqual(args.disk_smart_interval_minutes, 7)

    def test_json_and_yaml_configuration_survive_restart(self):
        """设置文件保存后重新读取保留关闭状态和分钟周期。"""
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            settings = dict(DEFAULT_SETTINGS, disk_allow_wakeup=False, disk_smart_interval_minutes=9)
            store.save(settings)
            restored = store.load()
            self.assertFalse(restored["disk_allow_wakeup"])
            self.assertEqual(restored["disk_smart_interval_minutes"], 9)
        args = create_argument_parser({"disk": {"allow_wakeup": False, "smart_interval_minutes": 9}}).parse_args([])
        self.assertFalse(args.disk_allow_wakeup)
        self.assertEqual(args.disk_smart_interval_minutes, 9)

    def test_active_mode_period_defaults_and_updates(self):
        """允许主动查询时仍按独立周期调度，延长和缩短均基于原采集时间。"""
        self.collector.configure_disk_policy(True, 30)
        descriptors = [("sda", "/dev/sda", "sat")]
        with mock.patch.object(self.collector, "_read_smart_health", return_value=1) as read:
            self.collector._disk_health(descriptors)
            self.clock.return_value = 1899
            self.collector._disk_health(descriptors)
            self.assertEqual(read.call_count, 1)
            self.clock.return_value = 1900
            self.collector._disk_health(descriptors)
            self.assertEqual(read.call_count, 2)
            self.collector.configure_disk_policy(True, 60)
            self.clock.return_value = 3700
            self.collector._disk_health(descriptors)
            self.assertEqual(read.call_count, 2)
            self.collector.configure_disk_policy(True, 1)
            read.assert_called()
            self.collector._disk_health(descriptors)
            self.assertEqual(read.call_count, 3)

    def test_raid_member_without_activity_blocks_volume_query(self):
        """一个 RAID 成员没有活动证据时不得查询整个卷的容量。"""
        self.names.return_value = ("sda", "sdb")
        self.counters.return_value["sdb"] = SimpleNamespace(read_bytes=100, write_bytes=0)
        with mock.patch.object(self.collector, "_linux_backing_disks", return_value=("sda", "sdb")):
            self.collector._passive_disk_details()
            self.advance()
            self.counters.return_value["sdb"] = SimpleNamespace(read_bytes=100, write_bytes=0)
            self.collector._passive_disk_details()
        self.usage.assert_not_called()

    def test_disappearing_disk_drops_cached_health(self):
        """磁盘消失时清理成功时间和容量，避免设备名重用继承旧数据。"""
        self.collector._passive_disk_details()
        self.advance()
        self.collector._passive_disk_details()
        self.names.return_value = ()
        self.partitions.return_value = []
        self.assertEqual(self.collector._passive_disk_details(), [])
        self.assertEqual(self.collector._protected_health_times, {})
        self.assertEqual(self.collector._protected_capacities, {})

    def test_smart_warning_exit_bits_remain_valid(self):
        """SMART 健康告警退出位不能被误判为休眠或查询失败。"""
        self.command.return_value = SimpleNamespace(returncode=8, stdout=json.dumps({"smart_status": {"passed": False}}))
        self.collector._passive_disk_details()
        self.advance()
        result = self.collector._passive_disk_details()
        self.assertEqual(result[0]["health"], 5)

    def test_empty_or_invalid_smart_data_is_not_activity_proof(self):
        """缺少有效数据时不能将成功退出当作允许访问卷的证据。"""
        for output in ("{}", "[]", "bad"):
            with self.subTest(output=output):
                self.command.return_value.stdout = output
                self.assertIsNone(self.collector._protected_smart("sda", True))

    def test_other_platforms_ignore_sleep_protection(self):
        """Windows 和 macOS 保持原有采集行为。"""
        for name in ("Windows", "Darwin"):
            with mock.patch.object(disk_policy.platform, "system", return_value=name):
                self.assertFalse(self.collector._protect_disk_sleep())

    def test_cpu_temperature_does_not_enumerate_all_sensors(self):
        """CPU 温度保护路径不调用会读取磁盘温度的全量 psutil 接口。"""
        with mock.patch("psutil.sensors_temperatures", create=True) as sensors, mock.patch("pathlib.Path.glob", return_value=[]):
            self.assertIsNone(CpuMetricsMixin._cpu_temperature(self.collector))
            sensors.assert_not_called()

    def test_linux_settings_save_applies_runtime_and_persists_yaml(self):
        """通过真实 Linux 设置桥接保存，验证热更新与 YAML 重载完整链路。"""
        from monitor_core.config import load_monitor_config
        service = MonitorService.__new__(MonitorService)
        service.arguments = create_argument_parser().parse_args([])
        service.collector = self.collector
        service.collector.ping_monitor = SimpleNamespace(target="")
        service.client = SimpleNamespace(is_connected=False)
        service._collection_coordinator = mock.Mock()
        for name in ("update_custom_data_runtime_settings", "_apply_runtime_qbittorrent",
                     "apply_display_config", "apply_dev_config", "_reset_adaptive_transmit_negotiation"):
            setattr(service, name, mock.Mock())
        bridge = LinuxInvokeBridge(service)
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "monitor.conf"
            config_path.write_text("{}\n", encoding="utf-8")
            service.arguments.config = str(config_path)
            result = bridge._save_settings({"settings": {"disk_allow_wakeup": False, "disk_smart_interval_minutes": 12}})
            self.assertTrue(result["persisted"])
            self.assertFalse(service.collector.disk_allow_wakeup)
            self.assertEqual(service.collector.disk_smart_interval_minutes, 12)
            restarted = create_argument_parser(load_monitor_config(config_path)).parse_args([])
            self.assertFalse(restarted.disk_allow_wakeup)
            self.assertEqual(restarted.disk_smart_interval_minutes, 12)
            with self.assertRaises(ValueError):
                bridge._save_settings({"settings": {"disk_smart_interval_minutes": True}})
            self.assertEqual(service.arguments.disk_smart_interval_minutes, 12)
            self.command.assert_not_called()

    def test_switch_to_protection_keeps_known_volume_capacity(self):
        """从主动模式切换后沿用已有单卷容量，不为填充界面读取磁盘。"""
        self.collector.configure_disk_policy(True, 30)
        self.collector._disk_task_snapshot = {"disks": [{
            "name": "sda", "devices": ["/dev/sda1"], "mountpoints": ["/volume1"],
            "used_bytes": 123, "total_bytes": 1000, "free_bytes": 877,
            "percent": 12.3, "capacity_updated_at": 100,
        }]}
        self.collector.configure_disk_policy(False, 30)
        result = self.collector._passive_disk_details()
        self.assertEqual(result[0]["used_bytes"], 123)
        self.assertTrue(result[0]["capacity_stale"])
        self.command.assert_not_called()
        self.usage.assert_not_called()

    def test_multiple_partitions_keep_all_mountpoints(self):
        """同盘多个分区不会因按磁盘名称合并而覆盖容量。"""
        self.partitions.return_value.append(SimpleNamespace(device="/dev/sda2", mountpoint="/volume2", fstype="ext4", opts="rw"))
        self.collector._passive_disk_details()
        self.advance()
        result = self.collector._passive_disk_details()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["used_bytes"], 200)
        self.assertEqual(result[0]["mountpoints"], ["/volume1", "/volume2"])

    def test_lvm_temperature_uses_hottest_member_without_statvfs(self):
        """温度任务保留逻辑卷最大成员温度语义，并且不触发容量读取。"""
        self.collector.configure_disk_policy(True, 30)
        self.collector._disk_task_snapshot = {"disks": [{"name": "dm-0", "devices": ["/dev/dm-0"]}]}
        with mock.patch.object(self.collector, "_linux_backing_disks", return_value=("sda", "sdb")), mock.patch.object(self.collector, "_disk_temperatures", return_value={"__physical_disks__": [
            {"name": "sda", "temperature_c": 30}, {"name": "sdb", "temperature_c": 40},
        ]}):
            result = self.collector._disk_temperature_details()
        self.assertEqual(result[0]["temperature_c"], 40)
        self.usage.assert_not_called()
