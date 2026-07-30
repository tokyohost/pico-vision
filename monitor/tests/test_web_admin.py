"""HTTP 管理页面与 WebSocket invoke 代理测试。"""

import asyncio
import socket
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest import mock

from aiohttp import ClientSession, WSServerHandshakeError

from monitor_core.arguments import create_argument_parser
from web_admin import HttpAdminServer


class _RecordingBridge:
    """记录代理调用参数的测试桥接对象。"""

    def __init__(self):
        """初始化最近一次调用记录。"""
        self.last_call = None

    def invoke(self, action, payload=None):
        """记录 action 和 payload 并返回标准成功响应。"""
        self.last_call = (action, payload)
        return {"ok": True, "data": {"action": action, "payload": payload}}


class HttpAdminServerTest(unittest.IsolatedAsyncioTestCase):
    """验证 HTTP 服务鉴权、静态页面和 RPC 消息契约。"""

    def setUp(self):
        """创建临时静态目录和空闲监听端口。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.static_directory = Path(self.temporary.name)
        (self.static_directory / "index.html").write_text(
            "<html lang=\"zh-CN\"></html>",
            encoding="utf-8",
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.bridge = _RecordingBridge()
        self.server = HttpAdminServer(
            bridge=self.bridge,
            static_directory=self.static_directory,
            host="127.0.0.1",
            port=self.port,
            auth="test-auth",
        )
        self.server.start()

    def tearDown(self):
        """停止测试服务并清理临时目录。"""
        self.server.stop()
        self.temporary.cleanup()

    async def test_health_and_index_are_available(self):
        """确认静态入口和健康检查无需鉴权即可访问。"""
        async with ClientSession() as session:
            async with session.get(
                "http://127.0.0.1:{}/api/health".format(self.port)
            ) as response:
                self.assertEqual(200, response.status)
                self.assertTrue((await response.json())["ok"])
            async with session.get(
                "http://127.0.0.1:{}/".format(self.port)
            ) as response:
                self.assertEqual(200, response.status)

    async def test_websocket_rejects_invalid_auth(self):
        """确认错误查询参数不能完成 WebSocket Upgrade。"""
        async with ClientSession() as session:
            with self.assertRaises(WSServerHandshakeError):
                await session.ws_connect(
                    "http://127.0.0.1:{}/ws?auth=wrong".format(self.port)
                )

    async def test_http_invoke_requires_header_auth(self):
        """确认额外 HTTP invoke 接口仅接受正确的鉴权 Header。"""
        url = "http://127.0.0.1:{}/api/invoke".format(self.port)
        payload = {"action": "device.status", "payload": {}}
        async with ClientSession() as session:
            async with session.post(url, json=payload) as response:
                self.assertEqual(401, response.status)
            async with session.post(
                url,
                json=payload,
                headers={"Authorization": "Bearer test-auth"},
            ) as response:
                self.assertEqual(200, response.status)
                self.assertTrue((await response.json())["ok"])

    async def test_websocket_proxies_invoke_with_request_id(self):
        """确认合法连接可以按请求编号代理 invoke 并返回结果。"""
        async with ClientSession() as session:
            socket_client = await session.ws_connect(
                "http://127.0.0.1:{}/ws?auth=test-auth".format(self.port)
            )
            await socket_client.send_json(
                {
                    "type": "invoke",
                    "id": "request-1",
                    "action": "device.status",
                    "payload": {"fresh": True},
                }
            )
            response = await asyncio.wait_for(
                socket_client.receive_json(),
                timeout=3,
            )
            self.assertEqual("request-1", response["id"])
            self.assertTrue(response["result"]["ok"])
            self.assertEqual(
                ("device.status", {"fresh": True}),
                self.bridge.last_call,
            )
            await socket_client.close()

    async def test_websocket_blocks_desktop_only_action(self):
        """确认桌面专属动作不会穿透到原业务桥接对象。"""
        async with ClientSession() as session:
            socket_client = await session.ws_connect(
                "http://127.0.0.1:{}/ws?auth=test-auth".format(self.port)
            )
            await socket_client.send_json(
                {
                    "type": "invoke",
                    "id": "request-2",
                    "action": "system.openDataDirectory",
                    "payload": {},
                }
            )
            response = await socket_client.receive_json()
            self.assertFalse(response["result"]["ok"])
            self.assertIsNone(self.bridge.last_call)
            await socket_client.close()

    async def test_server_automatically_uses_next_available_port(self):
        """确认配置端口被占用时服务会自动监听后续可用端口。"""
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            requested_port = occupied.getsockname()[1]
            fallback_server = HttpAdminServer(
                bridge=self.bridge,
                static_directory=self.static_directory,
                host="127.0.0.1",
                port=requested_port,
                auth="test-auth",
            )
            fallback_server.start()
            try:
                self.assertNotEqual(requested_port, fallback_server.port)
                async with ClientSession() as session:
                    async with session.get(
                        "http://127.0.0.1:{}/api/health".format(
                            fallback_server.port
                        )
                    ) as response:
                        self.assertEqual(200, response.status)
            finally:
                fallback_server.stop()


class HttpAdminConfigurationTest(unittest.TestCase):
    """验证 Linux HTTP 管理页面配置默认值和覆盖规则。"""

    def test_http_configuration_uses_expected_defaults(self):
        """确认 HTTP 管理页面默认关闭并使用 9876 端口。"""
        arguments = create_argument_parser().parse_args([])
        self.assertFalse(arguments.http_enabled)
        self.assertEqual(9876, arguments.http_port)
        self.assertEqual("0.0.0.0", arguments.http_host)

    def test_http_configuration_reads_yaml_values(self):
        """确认 Linux YAML 的 http 节点可以提供启动参数。"""
        arguments = create_argument_parser(
            {
                "http": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 9988,
                    "auth": "configured-auth",
                }
            }
        ).parse_args([])
        self.assertTrue(arguments.http_enabled)
        self.assertEqual("127.0.0.1", arguments.http_host)
        self.assertEqual(9988, arguments.http_port)
        self.assertEqual("configured-auth", arguments.http_auth)


class WindowsHttpAdminFailureTest(unittest.TestCase):
    """验证 Windows 端口绑定失败不会升级为应用未处理异常。"""

    def test_bind_failure_is_reported_without_raising(self):
        """确认服务启动异常会通知用户并由设置应用方法自行消化。"""
        webview_module = import_module("win.ui-web-api.webview")
        application = mock.Mock()
        application.settings = {
            "http_enabled": True,
            "http_port": 9876,
            "http_auth": "test-auth",
        }
        application.http_admin_server = None
        application.webview_bridge = mock.Mock()
        application.icon = mock.Mock()
        application._resource_path.return_value = Path("dist")
        with mock.patch.object(
            webview_module,
            "HttpAdminServer",
        ) as server_class:
            server_class.return_value.start.side_effect = PermissionError(13)
            result = webview_module.WebUiMixin._apply_http_admin_settings(
                application
            )
        self.assertFalse(result)
        application.icon.notify.assert_called_once()

    def test_fallback_port_is_saved_and_notified(self):
        """确认 Windows 自动切换端口后会持久化实际监听端口。"""
        webview_module = import_module("win.ui-web-api.webview")
        application = mock.Mock()
        application.settings = {
            "http_enabled": True,
            "http_port": 9876,
            "http_auth": "test-auth",
        }
        application.http_admin_server = None
        application.webview_bridge = mock.Mock()
        application.icon = mock.Mock()
        application._resource_path.return_value = Path("dist")
        with mock.patch.object(
            webview_module,
            "HttpAdminServer",
        ) as server_class:
            server_class.return_value.port = 9901
            result = webview_module.WebUiMixin._apply_http_admin_settings(
                application
            )
        self.assertTrue(result)
        self.assertEqual(9901, application.settings["http_port"])
        application.settings_store.save.assert_called_once_with(
            application.settings
        )
        application.icon.notify.assert_called_once()
