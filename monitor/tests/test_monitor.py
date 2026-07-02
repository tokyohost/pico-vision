"""验证系统快照结构和 Pico 串口协议的核心行为。"""

import unittest
from unittest import mock
from types import SimpleNamespace

from pico_client import PicoJsonClient
from pico_monitor import create_argument_parser
from system_monitor import SystemInformationCollector


class FakeSerial:
    """模拟能够确认 JSON 数据的 Pico 串口设备。"""

    def __init__(self):
        """初始化写入缓存和打开状态。"""
        self.is_open = True
        self.port = "TEST"
        self.written = bytearray()

    def write(self, data):
        """记录主机写入的协议字节。"""
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

    def test_screen_rotation_argument(self):
        """确认屏幕旋转参数只接受固件支持的方向。"""
        arguments = create_argument_parser().parse_args(["--screen-rotation", "180"])
        self.assertEqual(arguments.screen_rotation, 180)

    def test_ping_and_network_unit_arguments(self):
        """确认 Ping 默认地址和网络速率单位可以独立配置。"""
        defaults = create_argument_parser().parse_args([])
        self.assertEqual(defaults.ping_target, "www.baidu.com")
        arguments = create_argument_parser().parse_args(["--ping-target", "1.1.1.1", "--network-unit", "Mbps"])
        self.assertEqual(arguments.ping_target, "1.1.1.1")
        self.assertEqual(arguments.network_unit, "Mbps")

    def test_lcd_style_argument(self):
        """确认 monitor 可以选择固件提供的内置 LCD 样式。"""
        arguments = create_argument_parser().parse_args(["--lcd-style", "default"])
        self.assertEqual(arguments.lcd_style, "default")


class SystemCollectorTest(unittest.TestCase):
    """验证系统采集器输出 Pico 仪表盘需要的字段。"""

    @mock.patch.object(SystemInformationCollector, "_cpu_temperature", return_value=None)
    def test_collect_snapshot_structure(self, temperature):
        """确认完整快照包含四组核心硬件指标。"""
        del temperature
        collector = SystemInformationCollector("127.0.0.1")
        snapshot = collector.collect()
        self.assertEqual(snapshot["version"], 1)
        self.assertTrue({"cpu", "memory", "disk", "network"}.issubset(snapshot))

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


if __name__ == "__main__":
    unittest.main()
