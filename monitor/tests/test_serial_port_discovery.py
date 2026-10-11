"""验证 macOS 热插拔枚举容错及 Windows、Linux 原生枚举行为不变。"""

import stat
import unittest
from types import SimpleNamespace
from unittest import mock

from pico_client import PicoJsonClient
from serial_port_discovery import enumerate_serial_ports


class SerialPortDiscoveryTest(unittest.TestCase):
    """以真实观察到的缺失 locationID 异常覆盖枚举与重连入口。"""

    def test_success_retains_native_metadata(self):
        """枚举正常时保留设备身份和接口描述，不使用回退扫描。"""
        port = SimpleNamespace(device="/dev/cu.usbmodem7103", vid=0x303A)
        with mock.patch("serial_port_discovery.list_ports.comports", return_value=[port]), mock.patch(
                "serial_port_discovery.glob.glob") as fallback:
            self.assertEqual(enumerate_serial_ports(), [port])
            fallback.assert_not_called()

    def test_macos_missing_location_uses_only_existing_character_devices(self):
        """USB 位置信息缺失时跳过已拔出的节点和普通文件，并去重真实端口。"""
        def device_stat(device):
            """模拟一个已拔出节点、普通文件和真实 CDC 字符设备。"""
            if device.endswith("gone"):
                raise FileNotFoundError(device)
            return SimpleNamespace(st_mode=stat.S_IFREG if device.endswith("file") else stat.S_IFCHR)

        with mock.patch("serial_port_discovery.platform.system", return_value="Darwin"), mock.patch(
                "serial_port_discovery.list_ports.comports", side_effect=TypeError("NoneType >> int")), mock.patch(
                "serial_port_discovery.glob.glob", return_value=["/dev/cu.usbmodem7103", "/dev/cu.gone",
                                                               "/dev/cu.file", "/dev/cu.usbmodem7103"]), mock.patch(
                "serial_port_discovery.os.stat", side_effect=device_stat):
            self.assertEqual([port.device for port in enumerate_serial_ports()], ["/dev/cu.usbmodem7103"])

    def test_macos_disconnect_without_nodes_returns_empty(self):
        """设备完全拔出时返回空集合，保持服务等待下一次插入。"""
        with mock.patch("serial_port_discovery.platform.system", return_value="Darwin"), mock.patch(
                "serial_port_discovery.list_ports.comports", side_effect=OSError("device removed")), mock.patch(
                "serial_port_discovery.glob.glob", return_value=[]):
            self.assertEqual(PicoJsonClient.available_ports(), frozenset())

    def test_windows_and_linux_do_not_mask_enumeration_errors(self):
        """Mac 特定兼容逻辑不修改 Windows 或 Linux 的异常处理语义。"""
        for system in ("Windows", "Linux"):
            with self.subTest(system=system), mock.patch(
                    "serial_port_discovery.platform.system", return_value=system), mock.patch(
                    "serial_port_discovery.list_ports.comports", side_effect=TypeError("native error")), mock.patch(
                    "serial_port_discovery.glob.glob") as fallback:
                with self.assertRaises(TypeError):
                    enumerate_serial_ports()
                fallback.assert_not_called()

    def test_mac_reenumeration_restores_metadata_after_transient_failure(self):
        """下一轮原生枚举恢复后重新使用 VID/PID，不永久缓存回退信息。"""
        port = SimpleNamespace(device="/dev/cu.usbmodem7203", vid=0x303A)
        with mock.patch("serial_port_discovery.platform.system", return_value="Darwin"), mock.patch(
                "serial_port_discovery.list_ports.comports", side_effect=[TypeError("removed"), [port]]), mock.patch(
                "serial_port_discovery.glob.glob", return_value=[]):
            self.assertEqual(enumerate_serial_ports(), [])
            self.assertEqual(enumerate_serial_ports(), [port])


if __name__ == "__main__":
    unittest.main()
