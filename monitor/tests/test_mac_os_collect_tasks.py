"""验证 macOS 任务注册、原生解析、APFS 去重和采集器生命周期。"""

import io
import json
import os
import plistlib
import subprocess
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from constants import HISTORY_LENGTH
from collectTask.result_store import LockFreeSnapshotStore
from collectTask.system_tasks import create_system_tasks, system_task_classes
from collectTask.tasks.mac_os.cpu_percent import CpuPercentSampler
from collectTask.tasks.mac_os.disk import MacOsDiskMetrics, disk_identifier
from collectTask.tasks.mac_os.fps import MacOsFpsMonitor, parse_metal_hud_message
from collectTask.tasks.mac_os.native import number, plist_samples, read_plist, run_command
from collectTask.tasks.mac_os.runtime import MacOsGpuMonitor, MacOsPingMonitor, MacOsPowerMonitor
from collectTask.tasks.mac_os.system_strategy import MacOsCollectionStrategy
from collectTask.tasks.mac_os.telemetry import (
    MacOsTelemetry, empty_sample, parse_battery_power, parse_ioreg_gpu, parse_macmon, parse_powermetrics,
)
from collectTask.tasks.system_strategy import resolve_system_collection_strategy
from monitor_core.collectors.system_collector import SystemInformationCollector


MAC_TASK_NAMES = {"basic_information", "cpu_memory", "disk_capacity_health", "disk_temperature",
                  "disk_rate", "network", "gpu", "power", "fps"}


def completed(stdout=b"", returncode=0, stderr=b""):
    """创建原生命令返回值，测试不依赖真实 macOS 工具。"""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def partition(device, mountpoint, fstype="apfs"):
    """创建 psutil 分区数据替身。"""
    return SimpleNamespace(device=device, mountpoint=mountpoint, fstype=fstype, opts="rw")


def disk_owner():
    """构造独立磁盘后端所需的最小历史序列拥有者。"""
    return SimpleNamespace(last_disk_io=None, last_disk_io_time=None, disk_io_histories={})


class MacOsNativeTest(unittest.TestCase):
    """验证原生工具异常、样本损坏和数值越界的安全降级。"""

    def test_invalid_numbers_are_not_zero(self):
        """缺失、无穷大和布尔读数都必须保持空值。"""
        for value in (None, "bad", float("nan"), float("inf"), True, -1):
            self.assertIsNone(number(value))
        self.assertIsNone(number(101, maximum=100))
        self.assertEqual(number("0"), 0)

    def test_command_is_bounded_and_does_not_use_shell(self):
        """原生命令必须固定语言、设置超时并禁止 shell 拼接。"""
        with mock.patch("collectTask.tasks.mac_os.native.subprocess.run", return_value=completed()) as run:
            run_command(["/usr/sbin/diskutil", "info", "-plist", "disk0"], timeout=2)
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_missing_or_timed_out_command_returns_none(self):
        """缺少工具或命令超时不能让采集任务异常退出。"""
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("tool", 1)):
            with mock.patch("collectTask.tasks.mac_os.native.subprocess.run", side_effect=error):
                self.assertIsNone(run_command(["tool"]))

    def test_read_plist_handles_error_exit_and_broken_xml(self):
        """错误退出码和损坏 XML 都返回不可用状态。"""
        for result in (None, completed(b"bad"), completed(b"<?xml version='1.0'?><plist><dict></plist>"), completed(b"", 1)):
            with mock.patch("collectTask.tasks.mac_os.native.run_command", return_value=result):
                self.assertIsNone(read_plist(["tool"]))

    def test_plist_stream_ignores_partial_trailing_sample(self):
        """NUL 分隔的流只返回完整样本，不采用写到一半的数据。"""
        first, second = {"elapsed_ns": 1}, {"elapsed_ns": 2}
        stream = b"notice\n" + plistlib.dumps(first) + b"\0" + plistlib.dumps(second) + b"\0<?xml incomplete"
        self.assertEqual(plist_samples(stream), [first, second])


class MacOsTelemetryTest(unittest.TestCase):
    """验证 Intel、Apple Silicon、IOKit 和外置样本解析。"""

    def test_apple_silicon_frequency_utilization_power_and_smc(self):
        """频率按核心数量加权，利用率和毫瓦按实际单位转换。"""
        sample = parse_powermetrics({
            "processor": {"clusters": [{"freq_hz": 2e9, "cpus": [{}, {}]},
                                        {"freq_hz": 3e9, "cpus": [{}, {}, {}, {}]}],
                          "cpu_power": 3000, "gpu_power": 2000, "ane_power": 100},
            "gpu": {"idle_ratio": 0.25},
            "smc": {"cpu_die_temperature": 62.25, "gpu_die_temperature": 58.2},
        })
        self.assertEqual(sample["frequency_ghz"], 2.667)
        self.assertEqual(sample["gpu"]["percent"], 75)
        self.assertEqual(sample["gpu"]["temperature_c"], 58.2)
        self.assertEqual(sample["cpu_temperature_c"], 62.2)
        self.assertEqual(sample["power"]["watts"], 5.1)
        self.assertEqual(sample["power"]["scope"], "soc_cpu_gpu_ane")

    def test_intel_package_energy_uses_actual_duration(self):
        """Intel 封装焦耳除以实际采样秒数，不能假设每轮固定一秒。"""
        sample = parse_powermetrics({"elapsed_ns": 2e9, "processor": {"package_joules": 20, "freq_hz": 2.4e9},
                                    "GPU": [{"c_state_ratio": 0.4}]})
        self.assertEqual(sample["power"]["watts"], 10)
        self.assertEqual(sample["power"]["scope"], "cpu_package")
        self.assertEqual(sample["gpu"]["percent"], 60)

    def test_millijoules_are_not_mistaken_for_watts(self):
        """Apple Silicon 毫焦耳按纳秒采样周期换算。"""
        sample = parse_powermetrics({"elapsed_ns": 2e9, "processor": {"cpu_energy": 4000, "gpu_energy": 2000, "ane_energy": 0}})
        self.assertEqual(sample["power"]["watts"], 3)

    def test_unknown_values_remain_unavailable(self):
        """缺失字段和异常传感器读数不可成为零功耗或零温度。"""
        sample = parse_powermetrics({"processor": {}, "gpu": {"idle_ratio": 9}, "smc": {"cpu_die_temperature": 999}})
        self.assertIsNone(sample["gpu"]["percent"])
        self.assertIsNone(sample["cpu_temperature_c"])
        self.assertIsNone(sample["power"]["watts"])
        self.assertEqual(sample["power"]["scope"], "unavailable")

    def test_cpu_only_power_does_not_claim_entire_system(self):
        """只有 CPU 功耗时必须明确统计范围。"""
        sample = parse_powermetrics({"processor": {"cpu_power": 2300}})
        self.assertEqual(sample["power"]["watts"], 2.3)
        self.assertEqual(sample["power"]["scope"], "cpu_only")

    def test_ioreg_selects_busiest_gpu_without_summing_percent(self):
        """双显卡以最高负载设备作为当前协议 GPU 值。"""
        payload = [{"PerformanceStatistics": {"Device Utilization %": 12}},
                   {"VRAM,totalMB": 4096, "PerformanceStatistics": {"Device Utilization %": 82, "vramUsedBytes": 1024}}]
        gpu = parse_ioreg_gpu(payload)
        self.assertEqual(gpu["percent"], 82)
        self.assertEqual(gpu["dedicated_memory_total_bytes"], 4096 * 1024 * 1024)

    def test_apple_unified_memory_is_not_dedicated_vram(self):
        """没有 VRAM 容量的设备不能把内存字节数当作独立显存。"""
        gpu = parse_ioreg_gpu([{"PerformanceStatistics": {"Device Utilization %": 10, "vramUsedBytes": 1024}}])
        self.assertIsNone(gpu["dedicated_memory_used_bytes"])
        self.assertIsNone(gpu["dedicated_memory_total_bytes"])

    def test_battery_discharge_and_unsigned_negative_current(self):
        """有符号与无符号负电流都可换算，充电中不报告整机功耗。"""
        for current in (-2000, 2 ** 64 - 2000):
            power = parse_battery_power([{"ExternalConnected": False, "Amperage": current, "Voltage": 12000}])
            self.assertEqual(power["watts"], 24)
            self.assertEqual(power["scope"], "battery_discharge")
        self.assertIsNone(parse_battery_power([{"ExternalConnected": True, "Amperage": 2000, "Voltage": 12000}]))

    def test_macmon_active_ratio_and_core_frequency(self):
        """新版 macmon 优先使用活动比例，而非频率缩放后的比例。"""
        sample = parse_macmon({"gpu_active_ratio": 0.8, "gpu_scaled_ratio": 0.4,
                               "ecpu_cores": [{"freq_mhz": 1000}], "pcpu_cores": [{"freq_mhz": 3000}],
                               "temp": {"cpu_temp_avg": 50, "gpu_temp_avg": 45}, "sys_power": 12})
        self.assertEqual(sample["gpu"]["percent"], 80)
        self.assertEqual(sample["frequency_ghz"], 2)
        self.assertEqual(sample["cpu_temperature_c"], 50)
        self.assertEqual(sample["power"]["scope"], "system")

    def test_telemetry_expiry_clears_live_values(self):
        """后台采样停止后实时值不得持续发送。"""
        telemetry = MacOsTelemetry()
        sample = parse_powermetrics({"processor": {"combined_power": 3000}, "gpu": {"idle_ratio": 0.1}})
        telemetry._result = (sample, 7, 10)
        with mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=19):
            expired, version = telemetry.snapshot()
        self.assertEqual(version, 7)
        self.assertIsNone(expired["power"]["watts"])
        self.assertIsNone(expired["gpu"]["percent"])

    def test_snapshot_mutations_do_not_change_backend(self):
        """任务给快照添加历史字段不能污染共享遥测数据。"""
        telemetry = MacOsTelemetry()
        telemetry._result = (empty_sample(), 1, 10)
        with mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=11):
            sample, _ = telemetry.snapshot()
            sample["power"]["watts"] = 5
            self.assertIsNone(telemetry.snapshot()[0]["power"]["watts"])

    def test_unprivileged_process_does_not_execute_sudo_or_powermetrics(self):
        """普通用户未配置外置样本时，不自动执行提权工具。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            telemetry = MacOsTelemetry()
        with mock.patch("collectTask.tasks.mac_os.telemetry.os.geteuid", return_value=501, create=True), \
                mock.patch("collectTask.tasks.mac_os.telemetry.run_command") as run:
            self.assertIsNone(telemetry._read_power_sample())
        run.assert_not_called()

    def test_privileged_powermetrics_selects_available_samplers(self):
        """从工具帮助中选择存在的 sampler，Apple Silicon 不强制启用 smc。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            telemetry = MacOsTelemetry()
        payload = {"processor": {"cpu_power": 1000}}
        with mock.patch("collectTask.tasks.mac_os.telemetry.os.geteuid", return_value=0, create=True), \
                mock.patch("collectTask.tasks.mac_os.telemetry.run_command", side_effect=[completed(b"cpu_power gpu_power"), completed(plistlib.dumps(payload))]) as run:
            self.assertEqual(telemetry._read_power_sample(), payload)
        self.assertEqual(run.call_args.args[0][-1], "cpu_power,gpu_power")

    def test_external_sample_expires_even_if_file_mtime_is_future(self):
        """同一个外置文件不反复当作新样本，未来时间戳也不能绕过单调过期。"""
        path = mock.Mock()
        path.stat.return_value = SimpleNamespace(st_size=1000, st_mtime=2000, st_mtime_ns=2000000000000)
        path.open.return_value = io.BytesIO(plistlib.dumps({"processor": {"cpu_power": 1000}}))
        telemetry = MacOsTelemetry()
        telemetry.sample_file = "/external/sample.plist"
        with mock.patch("collectTask.tasks.mac_os.telemetry.Path", return_value=path), \
                mock.patch("collectTask.tasks.mac_os.telemetry.time.time", return_value=1000):
            with mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=10):
                self.assertIsNotNone(telemetry._read_power_sample())
            with mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=19):
                self.assertIsNone(telemetry._read_power_sample())

    def test_intel_nominal_frequency_is_explicit(self):
        """Intel psutil 降级频率明确标为标称值。"""
        telemetry = MacOsTelemetry()
        with mock.patch("collectTask.tasks.mac_os.telemetry.psutil.cpu_freq", return_value=SimpleNamespace(current=2400)):
            self.assertEqual(telemetry.cpu_frequency(), (2.4, "psutil_nominal"))

    def test_older_macmon_scaled_ratio_and_per_core_arrays(self):
        """旧版 JSON 的比例显式标为缩放负载，核心数组仍可计算平均频率。"""
        sample = parse_macmon({"gpu_usage": [400, 0.2], "ecpu_core_usages": [[1000, 0.1], [1000, 0.2]],
                               "pcpu_core_usages": [[2500, 0.2]], "sys_power": 8})
        self.assertEqual(sample["gpu"]["percent"], 20)
        self.assertEqual(sample["gpu"]["source"], "macmon_ioreport_scaled")
        self.assertEqual(sample["frequency_ghz"], 1.5)

    def test_macmon_zero_power_is_not_assumed_valid_on_unknown_hardware(self):
        """macmon 全零计数器可能不可用，不能误报整机零瓦。"""
        sample = parse_macmon({"sys_power": 0, "cpu_power": 0, "gpu_power": 0, "ane_power": 0})
        self.assertIsNone(sample["power"]["watts"])

    def test_macmon_error_uses_iokit_and_backs_off(self):
        """可选工具失败时退避重试，IOKit 基础 GPU 数据仍可发布。"""
        telemetry = MacOsTelemetry()
        telemetry._macmon_path = "/opt/homebrew/bin/macmon"
        with mock.patch.object(telemetry, "_read_power_sample", return_value=None), \
                mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=10), \
                mock.patch("collectTask.tasks.mac_os.telemetry.run_command", return_value=None) as run, \
                mock.patch("collectTask.tasks.mac_os.telemetry.read_plist", side_effect=lambda command, **_: [{"PerformanceStatistics": {"Device Utilization %": 40}}] if "IOAccelerator" in command else []):
            first, second = telemetry._sample(), telemetry._sample()
        self.assertEqual(first["gpu"]["percent"], 40)
        self.assertEqual(second["gpu"]["percent"], 40)
        self.assertEqual(run.call_count, 1)

    def test_telemetry_worker_starts_once_and_can_be_stopped(self):
        """重复启动不创建新线程，关闭能打断长采样周期。"""
        telemetry = MacOsTelemetry(interval=60)
        sampled = threading.Event()

        def sample():
            """完成一轮替身采样并通知主测试线程。"""
            sampled.set()
            return empty_sample()

        with mock.patch("collectTask.tasks.mac_os.telemetry.run_command", return_value=None), \
                mock.patch.object(telemetry, "_sample", side_effect=sample):
            telemetry.start()
            first_thread = telemetry._thread
            telemetry.start()
            self.assertIs(first_thread, telemetry._thread)
            self.assertTrue(sampled.wait(1))
            telemetry.close()
        self.assertFalse(first_thread.is_alive())


class MacOsDiskTest(unittest.TestCase):
    """验证 APFS 共享空间、物理盘映射、热插拔及读写速率。"""

    def setUp(self):
        """构造根卷快照与 Data 卷共享同一 APFS 容器的场景。"""
        self.owner = disk_owner()
        self.metrics = MacOsDiskMetrics(self.owner)
        self.metrics._smartctl_checked = True
        self.partitions = [partition("/dev/disk3s1s1", "/"), partition("/dev/disk3s5", "/System/Volumes/Data")]
        self.apfs = {"Containers": [{"ContainerReference": "disk3", "CapacityCeiling": 1000, "CapacityFree": 300,
                                     "PhysicalStores": [{"DeviceIdentifier": "disk0s2"}],
                                     "Volumes": [{"DeviceIdentifier": "disk3s1"}, {"DeviceIdentifier": "disk3s5"}]}]}

    def _details(self, payload=None):
        """用固定挂载列表和原生命令数据执行磁盘容量采集。"""
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_partitions", return_value=self.partitions), \
                mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_usage", return_value=SimpleNamespace(total=1000, free=300, used=700)), \
                mock.patch("collectTask.tasks.mac_os.disk.read_plist", side_effect=[payload or self.apfs, {"SMARTStatus": "Verified"}]):
            return self.metrics.details()

    def test_disk_identifiers_keep_physical_number_and_strip_snapshot(self):
        """disk0 不能被 Linux 规则截成 disk，根卷快照必须关联原卷。"""
        self.assertEqual(disk_identifier("/dev/rdisk0"), "disk0")
        self.assertEqual(disk_identifier("/dev/disk3s1s1"), "disk3s1")
        self.assertIsNone(disk_identifier("//server/share"))

    def test_apfs_root_and_data_capacity_are_counted_once(self):
        """两个 APFS 卷共享容量，汇总不能翻倍。"""
        disks = self._details()
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["name"], "disk0")
        self.assertEqual(disks[0]["total_bytes"], 1000)
        self.assertEqual(disks[0]["used_bytes"], 700)
        self.assertEqual(disks[0]["percent"], 70)
        self.assertEqual(disks[0]["health"], 1)
        self.assertEqual(len(disks[0]["mountpoints"]), 2)

    def test_fusion_drive_does_not_duplicate_container_capacity(self):
        """多物理存储的容器作为一组，不能向每个盘复制整个容量。"""
        self.apfs["Containers"][0]["PhysicalStores"].append({"DeviceIdentifier": "disk1s2"})
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_partitions", return_value=self.partitions), \
                mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_usage", return_value=SimpleNamespace(total=1000, free=300)), \
                mock.patch("collectTask.tasks.mac_os.disk.read_plist", side_effect=[self.apfs, {}, {}]):
            disks = self.metrics.details()
        self.assertEqual(disks[0]["name"], "disk0+disk1")
        self.assertEqual(disks[0]["total_bytes"], 1000)

    def test_missing_diskutil_still_deduplicates_apfs(self):
        """diskutil 不可用时按合成盘去重，基础容量仍可采集。"""
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_partitions", return_value=self.partitions), \
                mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_usage", return_value=SimpleNamespace(total=1000, free=300)), \
                mock.patch("collectTask.tasks.mac_os.disk.read_plist", return_value=None):
            disks = self.metrics.details()
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["total_bytes"], 1000)
        self.assertEqual(disks[0]["health"], 0)
        self.assertIsNone(disks[0]["temperature_c"])

    def test_network_and_virtual_filesystems_are_excluded(self):
        """远程挂载和 DMG 等虚拟介质不作为本地物理磁盘。"""
        self.partitions = [partition("//server/share", "/Volumes/share", "smbfs"), partition("/dev/disk7s1", "/Volumes/Image", "hfs")]
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_partitions", return_value=self.partitions), \
                mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_usage", return_value=SimpleNamespace(total=1000, free=300)), \
                mock.patch("collectTask.tasks.mac_os.disk.read_plist", side_effect=[{}, {"VirtualOrPhysical": "Virtual"}]):
            self.assertEqual(self.metrics.details(), [])

    def test_nonzero_smartctl_exit_can_report_failure_and_temperature(self):
        """SMART 故障退出码仍带有效 JSON，必须报告故障而不是丢弃。"""
        self.metrics._smartctl = "/opt/homebrew/sbin/smartctl"
        with mock.patch.object(self.metrics, "_info", return_value={}), \
                mock.patch("collectTask.tasks.mac_os.disk.run_command", return_value=completed(json.dumps({"smart_status": {"passed": False}, "temperature": {"current": 43}}).encode(), 8)):
            self.assertEqual(self.metrics._sensor("disk0"), {"health": 5, "temperature_c": 43})

    def test_disk_io_uses_physical_counters_and_handles_reset(self):
        """忽略 APFS 合成盘重复计数，并抑制计数器重置产生的负速率。"""
        counters = [{"disk0": SimpleNamespace(read_bytes=100, write_bytes=200), "disk3": SimpleNamespace(read_bytes=999, write_bytes=999)},
                    {"disk0": SimpleNamespace(read_bytes=300, write_bytes=600)},
                    {"disk0": SimpleNamespace(read_bytes=1, write_bytes=1)}]
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_io_counters", side_effect=counters), \
                mock.patch("collectTask.tasks.mac_os.disk.time.monotonic", side_effect=[10, 12, 14]):
            first = self.metrics.rates([{"name": "disk0"}])[0]
            second = self.metrics.rates([{"name": "disk0"}])[0]
            reset = self.metrics.rates([{"name": "disk0"}])[0]
        self.assertEqual(first["read_bps"], 0)
        self.assertEqual(second["read_bps"], 100)
        self.assertEqual(second["write_bps"], 200)
        self.assertEqual(reset["read_bps"], 0)
        self.assertEqual(len(second["read_history"]), HISTORY_LENGTH)

    def test_fusion_io_sums_distinct_backing_disks_once(self):
        """Fusion Drive 速率只相加不同物理存储，不叠加合成盘计数。"""
        self.owner.last_disk_io = {"disk0": SimpleNamespace(read_bytes=0, write_bytes=0), "disk1": SimpleNamespace(read_bytes=0, write_bytes=0)}
        self.owner.last_disk_io_time = 10
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_io_counters", return_value={"disk0": SimpleNamespace(read_bytes=100, write_bytes=200), "disk1": SimpleNamespace(read_bytes=300, write_bytes=400)}), \
                mock.patch("collectTask.tasks.mac_os.disk.time.monotonic", return_value=11):
            disk = self.metrics.rates([{"name": "disk0+disk1"}])[0]
        self.assertEqual((disk["read_bps"], disk["write_bps"]), (400, 600))

    def test_hotplug_invalidates_topology_and_smart_cache(self):
        """挂载关系变化时立即刷新映射和 SMART 缓存。"""
        with mock.patch("collectTask.tasks.mac_os.disk.read_plist", return_value=self.apfs) as read:
            self.metrics._refresh_topology(self.partitions)
            self.metrics._smart_cache["disk0"] = (10, {"health": 1})
            self.metrics._refresh_topology(self.partitions + [partition("/dev/disk8s1", "/Volumes/USB", "exfat")])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(self.metrics._smart_cache, {})

    def test_apfs_disk_image_backing_store_is_excluded(self):
        """APFS 磁盘映像不能因为有容器映射就被误报为物理磁盘。"""
        with mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_partitions", return_value=self.partitions), \
                mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_usage", return_value=SimpleNamespace(total=1000, free=300)), \
                mock.patch("collectTask.tasks.mac_os.disk.read_plist", side_effect=[self.apfs, {"VirtualOrPhysical": "Virtual"}]):
            self.assertEqual(self.metrics.details(), [])


class MacOsFpsTest(unittest.TestCase):
    """验证 Metal 日志解析、进程过滤、过期与后台进程关闭。"""

    def test_fps_and_frame_interval_are_real_frame_metrics(self):
        """显式 FPS 和帧间隔可解析，屏幕刷新率不可当作应用 FPS。"""
        self.assertEqual(parse_metal_hud_message("metal-HUD: FPS: 120"), 120)
        self.assertEqual(parse_metal_hud_message("metal-HUD: present_interval=20 ms"), 50)
        self.assertIsNone(parse_metal_hud_message("metal-HUD: refresh rate: 120 Hz"))
        self.assertIsNone(parse_metal_hud_message("unrelated FPS: 120"))

    def test_legacy_interval_pairs_exclude_gpu_time(self):
        """帧间隔与 GPU 耗时交错时只对帧间隔计算平均 FPS。"""
        self.assertEqual(parse_metal_hud_message("metal-HUD: 100, 0, 56.05, 20, 2, 30, 4"), 40)
        self.assertIsNone(parse_metal_hud_message("metal-HUD: 100, 0, 56.05, 20"))

    def test_pid_filter_and_expiry(self):
        """指定 PID 不接受其他应用的数据，三秒无日志后发布空值。"""
        with mock.patch.dict(os.environ, {"MONITOR_MAC_FPS_PID": "100"}):
            monitor = MacOsFpsMonitor()
        monitor._accept_event({"processID": 99, "eventMessage": "metal-HUD: FPS=120"}, now=10)
        self.assertIsNone(monitor.snapshot(10)["value"])
        monitor._accept_event({"processID": 100, "processImagePath": "/Applications/Game", "eventMessage": "metal-HUD: FPS=60"}, now=11)
        self.assertEqual(monitor.snapshot(12)["value"], 60)
        self.assertEqual(monitor.snapshot(12)["process_name"], "Game")
        self.assertIsNone(monitor.snapshot(15)["value"])

    def test_process_switch_resets_history(self):
        """最近日志应用切换时不能继承上一个应用的 FPS 曲线。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            monitor = MacOsFpsMonitor()
        monitor._accept_event({"processID": 100, "eventMessage": "metal-HUD: FPS=120"}, now=10)
        monitor._accept_event({"processID": 101, "eventMessage": "metal-HUD: FPS=60"}, now=11)
        snapshot = monitor.snapshot(12)
        self.assertEqual(snapshot["process_id"], 101)
        self.assertNotIn(120, snapshot["history"])

    def test_log_stream_shutdown_releases_process_and_pipe(self):
        """日志流正常结束后必须回收自有进程与输出管道。"""
        monitor = MacOsFpsMonitor()
        process = mock.Mock(stdout=io.StringIO(json.dumps({"processID": 100, "eventMessage": "metal-HUD: FPS=60"}) + "\n"))
        process.poll.return_value = 0
        with mock.patch("collectTask.tasks.mac_os.fps.subprocess.Popen", return_value=process), \
                mock.patch.object(monitor._stop, "wait", side_effect=lambda _: monitor._stop.set()):
            monitor._run()
        self.assertTrue(process.stdout.closed)
        self.assertIsNone(monitor._process)
        self.assertEqual(monitor.snapshot()["value"], 60)

    def test_log_process_is_terminated_on_close(self):
        """关闭 FPS 监控时只终止本监控器持有的子进程。"""
        monitor = MacOsFpsMonitor()
        process = mock.Mock()
        process.poll.return_value = None
        monitor._process = process
        monitor.close()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=1)
        self.assertTrue(monitor._stop.is_set())


class MacOsIntegrationTest(unittest.TestCase):
    """验证 Darwin 策略、全部任务执行和现有平台兼容性。"""

    def test_task_discovery_registers_every_metric_without_duplicates(self):
        """Darwin 发现全部九类任务，每个任务名称只出现一次。"""
        with mock.patch("platform.system", return_value="Darwin"):
            classes = system_task_classes()
        self.assertEqual({task.name for task in classes}, MAC_TASK_NAMES)
        self.assertEqual(len(classes), len(MAC_TASK_NAMES))
        self.assertTrue(all(task.__module__.startswith("collectTask.tasks.mac_os.") for task in classes))
        self.assertIsInstance(resolve_system_collection_strategy("Darwin"), MacOsCollectionStrategy)

    def test_windows_linux_freebsd_do_not_register_mac_tasks(self):
        """新任务不能污染其他平台的任务列表。"""
        for platform_name in ("Windows", "Linux", "FreeBSD"):
            with mock.patch("platform.system", return_value=platform_name):
                classes = system_task_classes()
            self.assertFalse(any(task.__module__.startswith("collectTask.tasks.mac_os.") for task in classes))

    def test_cpu_percent_uses_per_core_darwin_sampler(self):
        """CPU 百分比仍由实际核心时间计算，而非频率缩放比例。"""
        with mock.patch("collectTask.tasks.mac_os.cpu_percent.psutil.cpu_percent", return_value=[10, 30]) as sample:
            self.assertEqual(CpuPercentSampler(None).sample(0.5), 20)
        sample.assert_called_once_with(interval=0.5, percpu=True)

    def test_all_mac_tasks_publish_complete_snapshot_and_close(self):
        """验证采集器切换 macOS 后端，任务发布完整协议并关闭所有后台资源。"""
        with ExitStack() as stack:
            stack.enter_context(mock.patch("platform.system", return_value="Darwin"))
            for module, method in ((MacOsTelemetry, "start"), (MacOsPingMonitor, "start"), (MacOsFpsMonitor, "start")):
                stack.enter_context(mock.patch.object(module, method))
            collector = SystemInformationCollector("127.0.0.1")
            self.assertIsInstance(collector.gpu_monitor, MacOsGpuMonitor)
            self.assertIsInstance(collector.power_monitor, MacOsPowerMonitor)
            self.assertIsNone(collector.sensor_host)
            collector.mac_telemetry._result = (parse_macmon({"gpu_active_ratio": 0.75, "sys_power": 12,
                                                            "temp": {"cpu_temp_avg": 55, "gpu_temp_avg": 50}}), 1, 10)
            tasks = create_system_tasks(collector)
            stack.enter_context(mock.patch("collectTask.tasks.mac_os.telemetry.time.monotonic", return_value=11))
            stack.enter_context(mock.patch.object(collector.mac_telemetry, "cpu_frequency", return_value=(2.4, "macmon_ioreport")))
            stack.enter_context(mock.patch.object(collector, "_refresh_disk_hardware_state", return_value=False))
            stack.enter_context(mock.patch.object(collector.mac_disk, "details", return_value=[{"name": "disk0", "total_bytes": 1000, "used_bytes": 700, "free_bytes": 300, "percent": 70, "health": 1, "temperature_c": 40}]))
            stack.enter_context(mock.patch("collectTask.tasks.mac_os.disk.psutil.disk_io_counters", return_value={}))
            stack.enter_context(mock.patch("collectTask.tasks.mac_os.cpu_percent.psutil.cpu_percent", return_value=[10, 30]))
            stack.enter_context(mock.patch("collectTask.tasks.cpu_memory.psutil.virtual_memory", return_value=SimpleNamespace(percent=30, used=300, total=1000)))
            stack.enter_context(mock.patch.object(collector, "_local_ip", return_value="192.168.1.2"))
            stack.enter_context(mock.patch.object(collector, "_network_rates", return_value=(10, 20, 100, 200)))
            stack.enter_context(mock.patch.object(collector, "_network_link_speed", return_value=1000))
            store = LockFreeSnapshotStore({})
            for task in tasks:
                store.publish(task.collect())
            snapshot = store.snapshot()
            self.assertTrue({"cpu", "memory", "disk", "disks", "physical_disks", "gpu", "power", "network", "fps"}.issubset(snapshot))
            self.assertEqual(snapshot["cpu"]["percent"], 20)
            self.assertEqual(snapshot["cpu"]["temperature_c"], 55)
            self.assertEqual(snapshot["cpu"]["frequency_source"], "macmon_ioreport")
            self.assertEqual(snapshot["gpu"]["percent"], 75)
            self.assertEqual(snapshot["power"]["watts"], 12)
            self.assertEqual(snapshot["disk"]["total_bytes"], 1000)
            self.assertEqual(snapshot["network"]["upload_bps"], 10)
            self.assertIsNone(snapshot["fps"]["value"])
            json.dumps(snapshot, allow_nan=False)
            with mock.patch("monitor_core.collectors.system_collector.psutil.cpu_percent", return_value=20):
                legacy = collector.collect()
            self.assertEqual(legacy["cpu"]["frequency_ghz"], 2.4)
            self.assertEqual(legacy["cpu"]["temperature_c"], 55)
            self.assertEqual(legacy["disk"]["total_bytes"], 1000)
            with mock.patch.object(collector.mac_telemetry, "close") as telemetry_close, \
                    mock.patch.object(collector.ping_monitor, "close") as ping_close, \
                    mock.patch.object(collector.fps_monitor, "close") as fps_close:
                collector.close()
            telemetry_close.assert_called_once()
            ping_close.assert_called_once()
            fps_close.assert_called_once()

    def test_mac_ping_uses_millisecond_timeout(self):
        """Darwin -W 使用一千毫秒而不是 Linux 的一秒数值。"""
        monitor = MacOsPingMonitor("8.8.8.8")
        with mock.patch("collectTask.tasks.mac_os.runtime.run_command", return_value=completed(b"64 bytes: time=12.34 ms")) as run:
            self.assertEqual(monitor._probe(), 12.3)
        self.assertEqual(run.call_args.args[0], ["/sbin/ping", "-n", "-c", "1", "-W", "1000", "8.8.8.8"])

    def test_mac_ping_failure_does_not_fabricate_latency(self):
        """命令成功却没有延迟字段时也不能伪造一毫秒读数。"""
        for result in (None, completed(b"", 1), completed(b"no timing")):
            with mock.patch("collectTask.tasks.mac_os.runtime.run_command", return_value=result):
                self.assertIsNone(MacOsPingMonitor("8.8.8.8")._probe())


if __name__ == "__main__":
    unittest.main()
