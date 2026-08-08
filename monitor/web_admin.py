"""跨平台 HTTP 管理页面与 WebSocket 调用代理。"""

import asyncio
import json
import logging
import secrets
import threading
from pathlib import Path

from aiohttp import WSMsgType, web


LOGGER = logging.getLogger("pico-monitor.http")
DEFAULT_HTTP_PORT = 9876
HTTP_UNSUPPORTED_ACTIONS = {
    "device.firmware.select": "HTTP 页面不支持服务器本地固件选择",
    "device.firmware.updateLocal": "HTTP 页面不支持服务器本地固件选择",
    "device.sdk.select": "HTTP 页面不支持服务器本地镜像选择",
    "log.export": "HTTP 页面不支持原生文件保存对话框",
    "style.upload": "HTTP 页面不支持原生文件选择",
    "system.openDataDirectory": "HTTP 页面不支持打开服务器本地目录",
}


def create_random_auth():
    """生成适合放入配置文件的高强度随机鉴权密钥。"""
    return secrets.token_urlsafe(24)


class LinuxInvokeBridge:
    """为 Linux 无桌面服务提供与 pywebview 一致的最小调用协议。"""

    def __init__(self, service):
        """保存监控服务引用，供只读管理动作查询运行状态。"""
        self._service = service

    def _device_status(self):
        """返回 Linux 服务当前设备连接状态。"""
        client = self._service.client
        return {
            "connected": bool(client.is_connected),
            "port": getattr(client, "port_name", None),
            "transport": (
                "websocket"
                if getattr(client, "websocket_url", None)
                else "serial"
            ),
        }

    def _bootstrap(self):
        """构造现有 Vue 首屏所需的 Linux 兼容数据。"""
        from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
        from collectTask import system_task_defaults, system_task_zh_names

        arguments = self._service.arguments
        settings = {
            "port": arguments.port or "",
            "websocket_url": arguments.websocket_url or "",
            "force_usb_cdc": bool(arguments.force_usb_cdc),
            "websocket_client_name": arguments.websocket_client_name or "Monitor",
            "ping_target": arguments.ping_target,
            "interval": arguments.interval,
            "adaptive_transmit": bool(arguments.adaptive_transmit),
            "reconnect_interval": arguments.reconnect_interval,
            "serial_probe_interval": arguments.serial_probe_interval,
            "collection_task_intervals": dict(arguments.collection_task_intervals),
            "custom_data_configs": dict(arguments.custom_data_configs),
            "custom_data_enabled": dict(arguments.custom_data_enabled),
            "collection_task_logs": bool(arguments.collection_task_logs),
            "screen_rotation": arguments.screen_rotation,
            "lcd_brightness": arguments.lcd_brightness,
            "network_unit": arguments.network_unit,
            "lcd_style": arguments.lcd_style,
            "idle_style": arguments.idle_style,
            "idle_timeout": arguments.idle_timeout,
            "styles": [],
            "qbittorrent_enabled": bool(arguments.qbittorrent_enabled),
            "qbittorrent_address": arguments.qbittorrent_address or "",
            "qbittorrent_username": arguments.qbittorrent_username or "",
            "qbittorrent_password": arguments.qbittorrent_password or "",
            "qbittorrent_interval": arguments.qbittorrent_interval,
            "market_url": "",
        }
        return {
            "applicationName": "OmniWatch",
            "version": MONITOR_VERSION,
            "settings": settings,
            "styles": [],
            "taskNames": system_task_zh_names(),
            "defaultTasks": list(system_task_defaults()),
            "customDataPanels": [],
            "device": self._device_status(),
            "dataDirectory": "",
            "about": {
                "author": "tokyohost",
                "wechat": "hi2024FL",
                "repository": GITHUB_REPOSITORY,
                "qrDataUrl": "",
            },
        }

    def invoke(self, action, payload=None):
        """执行 Linux 已支持的 action，其余动作返回明确的不支持响应。"""
        del payload
        handlers = {
            "app.bootstrap": self._bootstrap,
            "device.status": self._device_status,
        }
        handler = handlers.get(str(action))
        if handler is None:
            return {
                "ok": False,
                "message": "Linux HTTP 管理页面暂不支持此操作：{}".format(action),
            }
        try:
            return {"ok": True, "data": handler()}
        except Exception as error:
            LOGGER.exception("执行 Linux HTTP 管理动作失败：%s", action)
            return {"ok": False, "message": str(error) or "操作失败"}


class HttpAdminServer:
    """在独立线程中承载 Vue 静态页面和 WebSocket invoke 代理。"""

    def __init__(self, bridge, static_directory, host, port, auth):
        """保存服务配置并初始化线程生命周期状态。"""
        self.bridge = bridge
        self.static_directory = Path(static_directory)
        self.host = str(host or "0.0.0.0")
        self.requested_port = int(port or DEFAULT_HTTP_PORT)
        self.port = self.requested_port
        self.auth = str(auth or "").strip() or create_random_auth()
        self._thread = None
        self._loop = None
        self._runner = None
        self._started = threading.Event()
        self._startup_error = None

    def _auth_matches(self, supplied):
        """使用恒定时间比较验证请求携带的鉴权密钥。"""
        return bool(supplied) and secrets.compare_digest(
            str(supplied),
            self.auth,
        )

    def _header_auth_matches(self, request):
        """验证普通 HTTP 接口的 Authorization Header。"""
        supplied = str(request.headers.get("Authorization") or "").strip()
        if supplied.lower().startswith("bearer "):
            supplied = supplied[7:].strip()
        return self._auth_matches(supplied)

    async def _health(self, request):
        """返回无需鉴权的服务健康状态。"""
        del request
        return web.json_response({"ok": True, "service": "omniwatch-http"})

    async def _runtime(self, request):
        """返回浏览器兼容层建立连接所需的公开运行参数。"""
        del request
        return web.json_response({"websocketPath": "/ws"})

    async def _http_invoke(self, request):
        """通过带鉴权 Header 的 HTTP 请求代理一次 invoke 调用。"""
        if not self._header_auth_matches(request):
            raise web.HTTPUnauthorized(text="鉴权失败")
        try:
            payload = await request.json()
            action = str(payload.get("action") or "")
            if not action:
                raise ValueError("缺少 action")
            unsupported = HTTP_UNSUPPORTED_ACTIONS.get(action)
            result = (
                {"ok": False, "message": unsupported}
                if unsupported
                else await asyncio.to_thread(
                    self.bridge.invoke,
                    action,
                    payload.get("payload") or {},
                )
            )
            return web.json_response(result)
        except web.HTTPException:
            raise
        except Exception as error:
            LOGGER.exception("处理 HTTP invoke 请求失败")
            return web.json_response(
                {"ok": False, "message": str(error) or "操作失败"},
                status=400,
            )

    async def _websocket(self, request):
        """在 Upgrade 阶段完成鉴权并代理带请求编号的 invoke 消息。"""
        if not self._auth_matches(request.query.get("auth", "")):
            raise web.HTTPUnauthorized(text="鉴权失败")
        socket = web.WebSocketResponse(
            heartbeat=30,
            max_msg_size=1024 * 1024,
        )
        await socket.prepare(request)
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                if message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
                continue
            request_id = None
            try:
                payload = json.loads(message.data)
                request_id = payload.get("id")
                action = str(payload.get("action") or "")
                if payload.get("type") != "invoke" or not request_id or not action:
                    raise ValueError("WebSocket invoke 请求格式无效")
                unsupported = HTTP_UNSUPPORTED_ACTIONS.get(action)
                result = (
                    {"ok": False, "message": unsupported}
                    if unsupported
                    else await asyncio.to_thread(
                        self.bridge.invoke,
                        action,
                        payload.get("payload") or {},
                    )
                )
                response = {"type": "result", "id": request_id, "result": result}
            except Exception as error:
                LOGGER.exception("处理 WebSocket invoke 请求失败")
                response = {
                    "type": "result",
                    "id": request_id,
                    "result": {"ok": False, "message": str(error) or "操作失败"},
                }
            await socket.send_json(response)
        return socket

    async def _index(self, request):
        """返回 Vue 单页应用入口。"""
        del request
        entry = self.static_directory / "index.html"
        if not entry.is_file():
            raise web.HTTPNotFound(text="Vue 构建产物不存在")
        return web.FileResponse(entry)

    async def _start_async(self):
        """创建 aiohttp 应用并开始监听管理端口。"""
        application = web.Application()
        application.router.add_get("/api/health", self._health)
        application.router.add_get("/api/runtime", self._runtime)
        application.router.add_post("/api/invoke", self._http_invoke)
        application.router.add_get("/ws", self._websocket)
        assets = self.static_directory / "assets"
        if assets.is_dir():
            application.router.add_static("/assets", assets)
        application.router.add_get("/", self._index)
        application.router.add_get("/{tail:.*}", self._index)
        self._runner = web.AppRunner(
            application,
            access_log=None,
        )
        await self._runner.setup()
        last_error = None
        for candidate in self._port_candidates():
            site = web.TCPSite(self._runner, self.host, candidate)
            try:
                await site.start()
                self.port = candidate
                if candidate != self.requested_port:
                    LOGGER.warning(
                        "HTTP 管理页面端口 %d 无法监听，已自动切换到 %d",
                        self.requested_port,
                        candidate,
                    )
                return
            except OSError as error:
                last_error = error
                if error.errno not in (13, 48, 98, 10013, 10048):
                    raise
        raise OSError(
            "从端口 {} 开始的候选范围均无法监听".format(
                self.requested_port
            )
        ) from last_error

    def _port_candidates(self):
        """从配置端口开始生成最多五百一十二个可回绕候选端口。"""
        candidate = self.requested_port
        for _ in range(512):
            yield candidate
            candidate += 1
            if candidate > 65535:
                candidate = 1024

    def _run(self):
        """运行 HTTP 服务线程的 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
            LOGGER.info(
                "HTTP 管理页面已启动：http://%s:%d，Auth=%s",
                self.host,
                self.port,
                self.auth,
            )
        except Exception as error:
            self._startup_error = error
            LOGGER.exception("HTTP 管理页面启动失败")
        finally:
            self._started.set()
        if self._startup_error is None:
            loop.run_forever()
        if self._runner is not None:
            loop.run_until_complete(self._runner.cleanup())
        loop.close()

    def start(self):
        """启动服务线程并同步报告端口占用等初始化错误。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._started.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="omniwatch-http-admin",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(5):
            raise RuntimeError("HTTP 管理页面启动超时")
        if self._startup_error is not None:
            if isinstance(self._startup_error, PermissionError):
                detail = (
                    "Windows 拒绝监听 {}:{}，端口可能被系统保留、"
                    "安全软件拦截或当前网络策略禁止".format(
                        self.host,
                        self.port,
                    )
                )
            elif isinstance(self._startup_error, OSError):
                detail = "{}:{} 监听失败，端口可能已被占用".format(
                    self.host,
                    self.port,
                )
            else:
                detail = str(self._startup_error)
            raise RuntimeError(
                "HTTP 管理页面启动失败：{}".format(detail)
            ) from self._startup_error

    def stop(self):
        """停止事件循环并等待 HTTP 服务线程退出。"""
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._thread = None
        self._loop = None
