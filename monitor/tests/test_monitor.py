"""验证系统快照结构和 Pico 串口协议的核心行为。"""

import os
import unittest
from unittest import mock
from types import SimpleNamespace

from pico_client import PicoJsonClient
from pico_monitor import MonitorService, create_argument_parser
from system_monitor import PowerMonitor, SystemInformationCollector


class FakeSerial:
    """模拟能够确认 JSON 数据的 Pico 串口设备。"""

    def __init__(self):
        """初始化写入缓存和打开状态。"""
        self.is_open = True
        self.port = "TEST"
        self.written = bytearray()
        self.write_calls = 0

    def write(self, data):
        """记录主机写入的协议字节。"""
        self.write_calls += 1
        self.written.extend(data)
        return len(data)

    def flush(self):
        """模拟立即完成串口发送。"""

    def readline(self):
        """返回 Pico JSON 接收确认。"""
        return b"ACK:JSON\n"

    def close(self):
        """将模拟串口切换为关闭状态。"""
        self.is_open = False


class PicoClientTest(unittest.TestCase):
    """验证 Pico 客户端生成兼容固件的 JSON 数据包。"""

    def test_send_json_packet(self):
        """确认数据包使用 JSON 前缀并以换行结束。"""
        client = PicoJsonClient()
        client.serial = FakeSerial()
        with self.assertLogs("pico-monitor.serial", level="INFO") as logs:
            client.send({"version": 1})
        self.assertTrue(client.serial.written.startswith(b"JSON:"))
        self.assertTrue(client.serial.written.endswith(b"\n"))
        self.assertTrue(any("Monitor -> Pico" in message for message in logs.output))
        self.assertTrue(any("Pico -> Monitor" in message for message in logs.output))

    def test_large_json_uses_larger_serial_chunks(self):
        """确认较大 JSON 不再拆分成大量六十四字节串口写入。"""
        client = PicoJsonClient()
        client.serial = FakeSerial()

        client.send({"payload": "x" * 2800})

        self.assertLessEqual(client.serial.write_calls, 6)

    def test_build_packet_for_development_mode(self):
        """确认开发模式打印内容与真实串口 JSON 协议行一致。"""
        packet = PicoJsonClient.build_packet({"host": "开发机"})

        self.assertTrue(packet.startswith(b"JSON:"))
        self.assertTrue(packet.endswith(b"\n"))
        self.assertEqual(len(packet) % 64, 0)
        self.assertIn(b'"host"', packet)

    def test_screen_rotation_argument(self):
        """确认屏幕旋转参数只接受固件支持的方向。"""
        arguments = create_argument_parser().parse_args(["--screen-rotation", "180"])
        self.assertEqual(arguments.screen_rotation, 180)

    def test_development_mode_argument(self):
        """确认命令行可以显式开启开发模式。"""
        arguments = create_argument_parser().parse_args(["--dev"])
        self.assertTrue(arguments.dev)

    def test_development_mode_stops_reconnecting_without_pico(self):
        """确认开发模式首次连接失败后直接进入 JSON 输出循环。"""
        service = MonitorService.__new__(MonitorService)
        service.arguments = SimpleNamespace(
            port=None,
            ping_target="127.0.0.1",
            interval=1.0,
            reconnect_interval=3.0,
            screen_rotation=0,
            network_unit="MB",
            lcd_style="horizontal_disk",
            dev=True,
        )
        service.stopping = mock.Mock()
        service.stopping.is_set.return_value = False
        service.client = mock.Mock()
        service.client.is_connected = False
        service.client.connect.side_effect = RuntimeError("未找到 Pico")
        service._run_development_loop = mock.Mock(return_value=0)

        result = service.run()

        self.assertEqual(result, 0)
        service.client.connect.assert_called_once_with()
        service._run_development_loop.assert_called_once_with()

    def test_ping_and_network_unit_arguments(self):
        """确认 Ping 默认地址和网络速率单位可以独立配置。"""
        defaults = create_argument_parser().parse_args([])
        self.assertEqual(defaults.ping_target, "www.baidu.com")
        arguments = create_argument_parser().parse_args(["--ping-target", "1.1.1.1", "--network-unit", "Mbps"])
        self.assertEqual(arguments.ping_target, "1.1.1.1")
        self.assertEqual(arguments.network_unit, "Mbps")

    def test_lcd_style_argument(self):
        """确认 monitor 可以选择固件提供的内置 LCD 样式。"""
        for style_name in ("default", "disk", "horizontal_disk"):
            arguments = create_argument_parser().parse_args(["--lcd-style", style_name])
            self.assertEqual(arguments.lcd_style, style_name)


class SystemCollectorTest(unittest.TestCase):
    """验证系统采集器输出 Pico 仪表盘需要的字段。"""

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures", return_value={})
    @mock.patch.object(SystemInformationCollector, "_cpu_temperature", return_value=None)
    def test_collect_snapshot_structure(self, temperature, disk_temperatures):
        """确认完整快照包含四组核心硬件指标。"""
        del temperature, disk_temperatures
        collector = SystemInformationCollector("127.0.0.1")
        snapshot = collector.collect()
        self.assertEqual(snapshot["version"], 1)
        self.assertTrue({"cpu", "memory", "disk", "disks", "physical_disks", "power", "network"}.issubset(snapshot))
        self.assertTrue({"watts", "source", "scope", "history"}.issubset(snapshot["power"]))

    def test_physical_disk_statistics_contains_temperature(self):
        """验证发送给 Pico 的物理磁盘统计包含温度和容量指标。"""
        statistics = SystemInformationCollector._physical_disk_statistics([
            {
                "name": "NVME0",
                "devices": ["C:"],
                "mountpoints": ["C:\\"],
                "used_bytes": 400,
                "total_bytes": 1000,
                "percent": 40,
                "temperature_c": 42.5,
            }
        ])

        self.assertEqual(statistics[0]["name"], "NVME0")
        self.assertEqual(statistics[0]["temperature_c"], 42.5)
        self.assertEqual(statistics[0]["total_bytes"], 1000)

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures")
    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_details_include_capacity_usage_and_temperature(self, disk_partitions, disk_usage, disk_temperatures):
        """确认每个磁盘明细包含容量、占用情况和对应温度。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", fstype="NTFS", opts="rw,fixed"),
        ]
        disk_usage.side_effect = (
            SimpleNamespace(total=1000, used=400, percent=40),
            SimpleNamespace(total=2000, used=500, percent=25),
        )
        disk_temperatures.return_value = {
            os.path.normcase("C:"): {"name": "NVME0", "temperature_c": 41.0},
            os.path.normcase("D:"): {"name": "SATA1", "temperature_c": 36.0},
        }
        collector = SystemInformationCollector.__new__(SystemInformationCollector)

        disks = collector._disk_details()

        self.assertEqual(len(disks), 2)
        self.assertEqual(disks[0]["name"], "NVME0")
        self.assertEqual(disks[0]["temperature_c"], 41.0)
        self.assertEqual((disks[1]["used_bytes"], disks[1]["total_bytes"], disks[1]["percent"]), (500, 2000, 25.0))

    @mock.patch.object(SystemInformationCollector, "_disk_temperatures")
    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_details_merge_partitions_on_same_physical_disk(self, disk_partitions, disk_usage, disk_temperatures):
        """确认同一物理硬盘的多个分区会聚合为一个磁盘明细。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", fstype="NTFS", opts="rw,fixed"),
        ]
        disk_usage.side_effect = (
            SimpleNamespace(total=1000, used=400, percent=40),
            SimpleNamespace(total=2000, used=500, percent=25),
        )
        sensor = {"name": "DISK0 NVME", "temperature_c": 40.0}
        disk_temperatures.return_value = {os.path.normcase("C:"): sensor, os.path.normcase("D:"): sensor}
        collector = SystemInformationCollector.__new__(SystemInformationCollector)

        disks = collector._disk_details()

        self.assertEqual(len(disks), 1)
        self.assertEqual((disks[0]["used_bytes"], disks[0]["total_bytes"], disks[0]["percent"]), (900, 3000, 30.0))
        self.assertEqual(disks[0]["mountpoints"], ["C:\\", "D:\\"])

    @mock.patch("system_monitor.psutil.disk_usage")
    @mock.patch("system_monitor.psutil.disk_partitions")
    def test_disk_usage_sums_all_local_disks(self, disk_partitions, disk_usage):
        """确认磁盘容量汇总全部本地分区并跳过重复挂载和光驱。"""
        disk_partitions.return_value = [
            SimpleNamespace(device="C:", mountpoint="C:\\", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\", opts="rw,fixed"),
            SimpleNamespace(device="D:", mountpoint="D:\\mirror", opts="rw,fixed"),
            SimpleNamespace(device="E:", mountpoint="E:\\", opts="ro,cdrom"),
        ]
        usages = {
            "C:\\": SimpleNamespace(total=1000, used=400),
            "D:\\": SimpleNamespace(total=2000, used=500),
        }
        disk_usage.side_effect = lambda mountpoint: usages[mountpoint]

        used, total, percent = SystemInformationCollector._disk_usage()

        self.assertEqual((used, total), (900, 3000))
        self.assertEqual(percent, 30.0)
        self.assertEqual(disk_usage.call_count, 2)

    @mock.patch("system_monitor.time.monotonic", side_effect=(10.0, 12.0))
    @mock.patch.object(PowerMonitor, "_read_energy_counters")
    def test_power_monitor_calculates_watts(self, energy_counters, monotonic):
        """确认相邻 RAPL 能耗读数能够换算为实时功耗瓦数。"""
        del monotonic
        energy_counters.side_effect = (
            {"package0": (1_000_000, 10_000_000)},
            {"package0": (5_000_000, 10_000_000)},
        )
        monitor = PowerMonitor()

        first = monitor.snapshot()
        second = monitor.snapshot()

        self.assertIsNone(first["watts"])
        self.assertEqual(second["watts"], 2.0)
        self.assertEqual(second["source"], "linux_rapl")


if __name__ == "__main__":
    unittest.main()
