"""验证 ESP32 主动 UDP 公告的设备端发送与 Monitor 解析。"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


MONITOR_ROOT = Path(__file__).resolve().parents[1]
ESP32_DISCOVERY_PATH = (
    Path(__file__).resolve().parents[2] / "esp32-s3" / "net" / "discovery.py"
)
if str(MONITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(MONITOR_ROOT))

from net.udp_discovery import UdpAnnouncementListener


class UdpAnnouncementListenerTest(unittest.TestCase):
    """确认 Monitor 只接受结构完整的发现公告。"""

    def test_valid_announcement_uses_datagram_source_ip(self):
        """公告中的自报 IP 不可信，连接地址必须采用 UDP 来源地址。"""
        payload = json.dumps({
            "magic": "FN_VISION_DISCOVERY",
            "version": 1,
            "ip": "10.0.0.99",
            "websocket_port": 8765,
            "websocket_path": "/pv1",
            "device_id": "device-1",
        }).encode("utf-8")

        candidate = UdpAnnouncementListener._parse(payload, "192.168.8.20")

        self.assertEqual("ws://192.168.8.20:8765/pv1", candidate.url)
        self.assertEqual("device-1", candidate.device_id)

    def test_invalid_protocol_is_ignored(self):
        """魔数或服务端口无效时不得生成连接候选。"""
        self.assertIsNone(
            UdpAnnouncementListener._parse(b'{"magic":"UNKNOWN"}', "192.168.8.20")
        )

    @mock.patch("net.udp_discovery.socket.socket")
    def test_received_announcement_is_written_to_runtime_log(self, socket_factory):
        """首次收到有效 UDP 公告时应记录来源、设备标识和候选地址。"""
        connection = socket_factory.return_value
        payload = json.dumps({
            "magic": "FN_VISION_DISCOVERY",
            "version": 1,
            "websocket_port": 8765,
            "websocket_path": "/pv1",
            "device_id": "device-1",
        }).encode("utf-8")
        connection.recvfrom.side_effect = (
            (payload, ("192.168.8.20", 49152)),
            TimeoutError(),
        )

        with self.assertLogs("pico-monitor.discovery", level="INFO") as captured:
            candidates = UdpAnnouncementListener(timeout=0.05).listen()

        self.assertEqual(["ws://192.168.8.20:8765/pv1"], [item.url for item in candidates])
        log_text = "\n".join(captured.output)
        self.assertIn("[Wi-Fi发现][UDP公告]", log_text)
        self.assertIn("来源=192.168.8.20:49152", log_text)
        self.assertIn("设备UUID=device-1", log_text)


class UdpDiscoveryAnnouncerTest(unittest.TestCase):
    """确认 ESP32 会同时发送组播与广播公告。"""

    @staticmethod
    def _load_module():
        """按文件路径加载固件模块，避免与 Monitor 的 net 包重名。"""
        specification = importlib.util.spec_from_file_location(
            "esp32_udp_discovery_test", ESP32_DISCOVERY_PATH
        )
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module

    def test_connected_device_sends_multicast_and_broadcast(self):
        """Wi-Fi 联网后一次更新应向两种局域网目标发送相同公告。"""
        module = self._load_module()
        wifi = mock.Mock()
        wifi.is_connected.return_value = True
        wifi.status.return_value = {"ip": "192.168.8.20"}
        connection = mock.Mock()
        socket_module = types.SimpleNamespace(
            AF_INET=2,
            SOCK_DGRAM=2,
            SOL_SOCKET=1,
            SO_BROADCAST=32,
            socket=mock.Mock(return_value=connection),
        )
        announcer = module.UdpDiscoveryAnnouncer(
            wifi,
            8765,
            "/pv1",
            device_id="device-1",
        )

        with mock.patch.dict(sys.modules, {"socket": socket_module}):
            self.assertTrue(announcer.update())

        self.assertEqual(2, connection.sendto.call_count)
        targets = [call.args[1] for call in connection.sendto.call_args_list]
        self.assertEqual(
            [("239.255.77.77", 37856), ("255.255.255.255", 37856)],
            targets,
        )


if __name__ == "__main__":
    unittest.main()
