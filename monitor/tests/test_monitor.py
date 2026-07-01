"""验证系统快照结构和 Pico 串口协议的核心行为。"""

import unittest
from unittest import mock

from pico_client import PicoJsonClient
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
        client.send({"version": 1})
        self.assertTrue(client.serial.written.startswith(b"JSON:"))
        self.assertTrue(client.serial.written.endswith(b"\n"))


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


if __name__ == "__main__":
    unittest.main()
