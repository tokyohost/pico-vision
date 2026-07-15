"""验证 ESP32-S3 WebSocket 客户端记录和优先级准入规则。"""

import tempfile
import unittest
import json as standard_json
import types
from pathlib import Path
from unittest import mock

import sys


ESP32_ROOT = Path(__file__).resolve().parents[2] / "esp32-s3"
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

from net.websocket_clients import (
    MAX_WEBSOCKET_CLIENT_REGISTRY_BYTES,
    WebSocketClientRegistry,
)
from net.websocket import WebSocketTransport
import net.websocket_clients as websocket_clients_module


class FakeWifiManager:
    """提供设备端 WebSocket 策略所需的最小联网状态。"""

    def is_connected(self):
        """测试期间始终报告 Wi-Fi 已连接。"""
        return True

    def status(self):
        """返回空的 Wi-Fi 状态。"""
        return {}

    def update(self):
        """忽略测试中的 Wi-Fi 状态推进。"""


class FakeSocket:
    """记录握手响应、关闭状态的内存套接字。"""

    def __init__(self):
        """初始化空发送记录和打开状态。"""
        self.sent = []
        self.closed = False

    def send(self, data):
        """记录服务端发送的数据并报告完整写入。"""
        self.sent.append(bytes(data))
        return len(data)

    def close(self):
        """标记套接字已经关闭。"""
        self.closed = True


class FailingPersistenceRegistry:
    """模拟客户端身份有效但 Flash 持久化失败的记录器。"""

    def observe(self, client_id, name, peer):
        """返回可准入身份，避免测试依赖真实文件。"""
        return {
            "id": client_id,
            "name": name,
            "enabled": True,
            "priority": 0,
            "connections": 0,
            "last_peer": peer,
        }

    def record_connected(self, client_id, peer):
        """模拟设备 Flash 在握手完成时写入失败。"""
        raise OSError("flash busy")

    def flush(self):
        """模拟候选连接清单刷新失败。"""
        raise OSError("flash busy")

    def list_clients(self, active_client_id=None):
        """返回空清单以满足传输状态接口。"""
        return []


class WebSocketClientRegistryTest(unittest.TestCase):
    """确认客户端策略可持久化、排序并正确更新。"""

    def test_client_record_is_persisted_without_losing_policy(self):
        """重新加载记录后应保留禁用状态、优先级和成功连接次数。"""
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "clients.json")
            registry = WebSocketClientRegistry(path)
            registry.observe("client-a", "工作站甲", "192.168.1.10")
            registry.record_connected("client-a", "192.168.1.10")
            registry.update("client-a", enabled=False, priority=8)

            restored = WebSocketClientRegistry(path).get("client-a")

        self.assertEqual("工作站甲", restored["name"])
        self.assertFalse(restored["enabled"])
        self.assertEqual(8, restored["priority"])
        self.assertEqual(1, restored["connections"])

    def test_clients_are_sorted_by_descending_priority(self):
        """客户端列表应优先展示高优先级记录并标记当前连接。"""
        with tempfile.TemporaryDirectory() as directory:
            registry = WebSocketClientRegistry(str(Path(directory) / "clients.json"))
            registry.observe("low", "低优先级", "192.168.1.11")
            registry.observe("high", "高优先级", "192.168.1.12")
            registry.update("high", priority=10)
            clients = registry.list_clients(active_client_id="high")

        self.assertEqual(["high", "low"], [item["id"] for item in clients])
        self.assertTrue(clients[0]["active"])

    def test_persistence_uses_micropython_compatible_json_api(self):
        """持久化不得向 MicroPython JSON 传递不支持的 ensure_ascii 参数。"""
        compatible_json = types.SimpleNamespace(
            dumps=lambda payload: standard_json.dumps(payload),
            loads=lambda payload: standard_json.loads(payload),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "clients.json")
            registry = WebSocketClientRegistry(path)
            registry.observe("client-a", "工作站甲", "192.168.1.10")
            with mock.patch.object(websocket_clients_module, "json", compatible_json):
                registry.record_connected("client-a", "192.168.1.10")
            restored = standard_json.loads(Path(path).read_text(encoding="utf-8"))

        self.assertEqual("client-a", restored["clients"][0]["id"])

    def test_registry_rejects_unbounded_new_client_identities(self):
        """达到容量上限后应拒绝新身份，防止扫描或恶意握手耗尽内存。"""
        with tempfile.TemporaryDirectory() as directory:
            registry = WebSocketClientRegistry(
                str(Path(directory) / "clients.json"),
                maximum_clients=2,
            )
            registry.observe("client-a", "甲", "192.168.1.10")
            registry.observe("client-b", "乙", "192.168.1.11")

            with self.assertRaisesRegex(ValueError, "WEBSOCKET_CLIENT_LIMIT_REACHED"):
                registry.observe("client-c", "丙", "192.168.1.12")

    def test_oversized_registry_file_is_ignored(self):
        """异常超大记录文件不得被完整载入设备内存。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(
                " " * (MAX_WEBSOCKET_CLIENT_REGISTRY_BYTES + 1),
                encoding="utf-8",
            )

            registry = WebSocketClientRegistry(str(path))

        self.assertEqual([], registry.list_clients())


class WebSocketClientPriorityTest(unittest.TestCase):
    """确认候选 WebSocket 客户端严格按优先级抢占唯一连接。"""

    @staticmethod
    def _request(client_id, name):
        """构造携带客户端身份的 WebSocket 升级请求。"""
        return (
            "GET /pv1 HTTP/1.1\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "X-OmniWatch-Client-Id: {}\r\n"
            "X-OmniWatch-Device-Name: {}\r\n\r\n"
        ).format(client_id, name).encode("utf-8")

    def _transport(self, directory):
        """创建绑定临时客户端记录文件的传输策略。"""
        registry = WebSocketClientRegistry(str(Path(directory) / "clients.json"))
        return WebSocketTransport(FakeWifiManager(), client_registry=registry), registry

    def test_higher_priority_client_preempts_current_connection(self):
        """高优先级客户端握手成功后应关闭旧连接并成为唯一活动连接。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, registry = self._transport(directory)
            old_socket = FakeSocket()
            new_socket = FakeSocket()
            registry.observe("low", "低优先级", "192.168.1.10")
            registry.observe("high", "高优先级", "192.168.1.11")
            registry.update("high", priority=10)
            transport._client = old_socket
            transport._peer = ("192.168.1.10", 1000)
            transport._http_buffer = None
            transport._client_identity = registry.get("low")
            transport._pending_client = new_socket
            transport._pending_peer = ("192.168.1.11", 1001)

            transport._upgrade_candidate(
                new_socket,
                transport._pending_peer,
                self._request("high", "高优先级"),
                pending=True,
            )

            self.assertTrue(old_socket.closed)
            self.assertIs(new_socket, transport._client)
            self.assertEqual("high", transport._client_identity["id"])
            self.assertTrue(new_socket.sent[0].startswith(b"HTTP/1.1 101"))

    def test_equal_or_lower_priority_client_is_rejected(self):
        """同级或低优先级候选应收到 409，且不得影响当前活动连接。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, registry = self._transport(directory)
            active_socket = FakeSocket()
            candidate_socket = FakeSocket()
            registry.observe("active", "当前客户端", "192.168.1.20")
            registry.update("active", priority=5)
            transport._client = active_socket
            transport._peer = ("192.168.1.20", 1000)
            transport._http_buffer = None
            transport._client_identity = registry.get("active")
            transport._pending_client = candidate_socket
            transport._pending_peer = ("192.168.1.21", 1001)

            transport._upgrade_candidate(
                candidate_socket,
                transport._pending_peer,
                self._request("candidate", "候选客户端"),
                pending=True,
            )

            self.assertIs(active_socket, transport._client)
            self.assertFalse(active_socket.closed)
            self.assertTrue(candidate_socket.closed)
            self.assertTrue(candidate_socket.sent[0].startswith(b"HTTP/1.1 409"))

    def test_disabling_active_client_disconnects_after_command_response(self):
        """禁用当前客户端时应先发送命令响应，再关闭会话。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, registry = self._transport(directory)
            active_socket = FakeSocket()
            registry.observe("active", "当前客户端", "192.168.1.20")
            transport._client = active_socket
            transport._peer = ("192.168.1.20", 1000)
            transport._http_buffer = None
            transport._client_identity = registry.get("active")

            transport.update_client("active", enabled=False)

            self.assertFalse(active_socket.closed)
            self.assertGreater(transport.write(b"PV1:COMMAND:0:0000:{}\n"), 0)
            self.assertTrue(active_socket.closed)
            self.assertTrue(active_socket.sent)

    def test_incomplete_primary_and_pending_handshakes_expire(self):
        """两个握手槽位都必须超时释放，避免半连接永久堵死监听服务。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, _ = self._transport(directory)
            primary = FakeSocket()
            pending = FakeSocket()
            transport._client = primary
            transport._http_buffer = bytearray()
            transport._accepted_ms = 0
            transport._pending_client = pending
            transport._pending_http_buffer = bytearray()
            transport._pending_accepted_ms = 0

            transport._expire_handshakes(transport._HANDSHAKE_TIMEOUT_MS)

            self.assertTrue(primary.closed)
            self.assertTrue(pending.closed)
            self.assertIsNone(transport._client)
            self.assertIsNone(transport._pending_client)

    def test_primary_handshake_header_has_hard_size_limit(self):
        """主握手头超过上限时必须立即关闭，不能持续扩张设备堆内存。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, _ = self._transport(directory)
            primary = FakeSocket()
            primary.recv = lambda size: b"x" * min(size, 32)
            transport._client = primary
            transport._http_buffer = bytearray(b"x" * transport._MAX_HTTP_HEADER_BYTES)

            transport._read_socket()

            self.assertTrue(primary.closed)
            self.assertIsNone(transport._client)

    def test_persistence_failure_does_not_kill_successful_handshake(self):
        """客户端记录写入失败时连接仍应完成，设备主循环不得退出。"""
        transport = WebSocketTransport(
            FakeWifiManager(),
            client_registry=FailingPersistenceRegistry(),
        )
        client = FakeSocket()
        transport._client = client
        transport._peer = ("192.168.1.30", 1000)
        transport._http_buffer = bytearray()

        transport._upgrade_candidate(
            client,
            transport._peer,
            self._request("client-a", "工作站甲"),
            pending=False,
        )

        self.assertTrue(transport.is_connected())
        self.assertFalse(client.closed)
        self.assertTrue(client.sent[0].startswith(b"HTTP/1.1 101"))

    def test_discovery_handshake_does_not_touch_active_client_or_registry(self):
        """局域网扫描握手不得登记身份，也不得断开当前业务连接。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, registry = self._transport(directory)
            active_socket = FakeSocket()
            discovery_socket = FakeSocket()
            registry.observe("active", "当前客户端", "192.168.1.20")
            transport._client = active_socket
            transport._peer = ("192.168.1.20", 1000)
            transport._http_buffer = None
            transport._client_identity = registry.get("active")
            transport._pending_client = discovery_socket
            transport._pending_peer = ("192.168.1.21", 1001)
            request = (
                b"GET /pv1 HTTP/1.1\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                b"X-OmniWatch-Discovery: 1\r\n\r\n"
            )

            transport._upgrade_candidate(
                discovery_socket,
                transport._pending_peer,
                request,
                pending=True,
            )

            self.assertIs(active_socket, transport._client)
            self.assertFalse(active_socket.closed)
            self.assertTrue(discovery_socket.closed)
            self.assertTrue(discovery_socket.sent[0].startswith(b"HTTP/1.1 101"))
            self.assertEqual(["active"], [item["id"] for item in registry.list_clients()])

    def test_unexpected_handshake_error_only_resets_websocket_service(self):
        """未预见的握手异常不得越过传输边界导致设备主循环假死。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, _ = self._transport(directory)
            server = FakeSocket()
            transport._server = server

            with mock.patch.object(transport, "_open_server"), mock.patch.object(
                transport, "_accept"
            ), mock.patch.object(
                transport, "_read_socket", side_effect=TypeError("bad handshake")
            ):
                transport.update()

            self.assertTrue(server.closed)
            self.assertIsNone(transport._server)

    def test_repeated_discovery_handshakes_leave_no_session_or_identity(self):
        """连续局域网扫描不得累积连接、缓冲或客户端身份记录。"""
        with tempfile.TemporaryDirectory() as directory:
            transport, registry = self._transport(directory)
            request = (
                b"GET /pv1 HTTP/1.1\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: Upgrade\r\n"
                b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                b"X-OmniWatch-Discovery: 1\r\n\r\n"
            )

            for index in range(256):
                client = FakeSocket()
                transport._client = client
                transport._peer = ("192.168.1.{}".format(index % 254 + 1), 1000)
                transport._http_buffer = bytearray()
                transport._upgrade_candidate(
                    client,
                    transport._peer,
                    request,
                    pending=False,
                )
                self.assertTrue(client.closed)

            self.assertIsNone(transport._client)
            self.assertIsNone(transport._client_identity)
            self.assertEqual([], registry.list_clients())


if __name__ == "__main__":
    unittest.main()
