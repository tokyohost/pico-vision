"""验证设备 Wi-Fi 扫描状态恢复和忘记网络行为。"""

import os
import tempfile
import unittest

from net.wifi import WifiManager


class FakeWlan:
    """模拟会在首次扫描时发生内部状态冲突的无线网卡。"""

    def __init__(self):
        """初始化网卡状态和调用记录。"""
        self.active_calls = []
        self.disconnect_count = 0
        self.scan_count = 0

    def isconnected(self):
        """返回模拟网卡尚未连接。"""
        return False

    def disconnect(self):
        """记录取消后台连接的次数。"""
        self.disconnect_count += 1

    def active(self, enabled):
        """记录 STA 接口启停顺序。"""
        self.active_calls.append(enabled)

    def scan(self):
        """首次抛出内部状态错误，重置后返回两个热点。"""
        self.scan_count += 1
        if self.scan_count == 1:
            raise OSError("Wifi Internal State Error")
        return [
            ("附近网络一".encode("utf-8"), bytes((1, 2, 3, 4, 5, 6)), 1, -35, 3, False),
            ("附近网络二".encode("utf-8"), bytes((6, 5, 4, 3, 2, 1)), 6, -50, 0, False),
        ]

    def status(self):
        """返回模拟网卡的空闲状态。"""
        return 0


class WifiManagerTest(unittest.TestCase):
    """验证 Wi-Fi 管理器面向配网页面的关键行为。"""

    def create_manager(self, config_path):
        """创建绕过真实 network 模块的 Wi-Fi 管理器。"""
        manager = WifiManager.__new__(WifiManager)
        manager._config_path = config_path
        manager._reconnect_interval_ms = 5000
        manager._wlan = FakeWlan()
        manager._ssid = "已保存网络"
        manager._password = "测试密钥"
        manager._last_error = "WIFI_CONNECT_ERROR:Wifi Internal State Error"
        manager._next_reconnect_ms = 0
        manager._scan_in_progress = False
        manager._sleep_ms = lambda duration_ms: None
        return manager

    def test_scan_recovers_connection_state_and_returns_all_networks(self):
        """确认不可用的已保存网络不会阻止本次全量扫描。"""
        manager = self.create_manager("wifi_config.json")

        networks = manager.scan()

        self.assertEqual(["附近网络一", "附近网络二"], [item["ssid"] for item in networks])
        self.assertEqual(2, manager._wlan.scan_count)
        self.assertEqual([False, True], manager._wlan.active_calls)
        self.assertEqual(1, manager._wlan.disconnect_count)

    def test_forget_removes_saved_credentials_and_configuration(self):
        """确认忘记网络会断开连接、清空内存凭据并删除配置。"""
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "wifi_config.json")
            with open(config_path, "w", encoding="utf-8") as target:
                target.write("{}")
            manager = self.create_manager(config_path)

            status = manager.forget("已保存网络")

            self.assertIsNone(manager._ssid)
            self.assertIsNone(manager._password)
            self.assertFalse(os.path.exists(config_path))
            self.assertIsNone(status["ssid"])


if __name__ == "__main__":
    unittest.main()
