"""跨平台 HTTP 管理页面与 WebSocket 调用代理。"""

import asyncio
import base64
import json
import logging
import mimetypes
import os
import queue
import secrets
import shutil
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

import custom_data
from monitor_core.ui_helpers import (
    extract_style_package,
    load_style_assets,
    merge_wifi_networks,
    normalize_style_catalog,
    persist_style_package_assets,
    wifi_security_label,
    wifi_state_label,
)


LOGGER = logging.getLogger("pico-monitor.http")
DEFAULT_HTTP_PORT = 9876
HTTP_UPLOAD_TTL_SECONDS = 30 * 60
HTTP_UPLOAD_MAXIMUM_SIZE = 256 * 1024 * 1024
HTTP_UPLOAD_SPECS = {
    "data": {"maximum": 50 * 1024 * 1024, "directory": False},
    "data-directory": {"maximum": 50 * 1024 * 1024, "directory": True},
    "style": {"maximum": 20 * 1024 * 1024, "directory": False},
    "firmware": {"maximum": 200 * 1024 * 1024, "directory": False},
    "sdk": {"maximum": 100 * 1024 * 1024, "directory": False},
}
HTTP_UPLOAD_ACTION_KINDS = {
    "data.import": "data",
    "data.importDirectory": "data-directory",
    "style.upload": "style",
    "device.firmware.select": "firmware",
    "device.firmware.updateLocal": "firmware",
    "device.sdk.select": "sdk",
    "device.sdk.flash": "sdk",
}
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
        self._upload_root = Path(tempfile.mkdtemp(prefix="omniwatch-http-upload-"))
        self._uploads = {}
        self._upload_lock = threading.RLock()
        self._upload_cleanup_stop = threading.Event()
        self._upload_cleanup_thread = None
        attach_http_server = getattr(bridge, "attach_http_server", None)
        if callable(attach_http_server):
            attach_http_server(self)

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

    def _cleanup_uploads(self, force=False):
        """删除已过期或服务停止时不再需要的浏览器上传临时目录。"""
        now = time.monotonic()
        with self._upload_lock:
            upload_ids = [
                upload_id
                for upload_id, item in self._uploads.items()
                if force or item["expires"] <= now
            ]
            items = [self._uploads.pop(upload_id) for upload_id in upload_ids]
        for item in items:
            shutil.rmtree(item["directory"], ignore_errors=True)

    def _upload_cleanup_loop(self):
        """定期清理无人继续使用的浏览器上传临时目录。"""
        while not self._upload_cleanup_stop.wait(60):
            self._cleanup_uploads()

    @staticmethod
    def _upload_relative_path(filename, directory):
        """规范化浏览器文件名，拒绝绝对路径和目录穿越。"""
        raw_name = str(filename or "").replace("\\", "/")
        relative = PurePosixPath(raw_name)
        if directory:
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ValueError("上传目录包含不安全文件路径")
            parts = tuple(part for part in relative.parts if part not in ("", "."))
        else:
            name = relative.name
            if not name or name in (".", ".."):
                raise ValueError("上传文件名无效")
            parts = (name,)
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError("上传文件名无效")
        return Path(*parts)

    async def _upload(self, request):
        """接收浏览器 multipart 文件并返回一次性 uploadId。"""
        if not self._header_auth_matches(request):
            raise web.HTTPUnauthorized(text="鉴权失败")
        kind = str(request.match_info.get("kind") or "").strip()
        specification = HTTP_UPLOAD_SPECS.get(kind)
        if specification is None:
            raise web.HTTPNotFound(text="不支持的上传类型")
        self._cleanup_uploads()
        upload_id = secrets.token_urlsafe(18)
        upload_directory = self._upload_root / upload_id
        upload_directory.mkdir(parents=True, exist_ok=False)
        file_paths = []
        total_size = 0
        try:
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                filename = getattr(part, "filename", None)
                if not filename:
                    await part.read(decode=False)
                    continue
                relative_path = self._upload_relative_path(
                    filename,
                    bool(specification["directory"]),
                )
                target = upload_directory.joinpath(relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                file_size = 0
                with target.open("wb") as output:
                    while True:
                        chunk = await part.read_chunk(64 * 1024)
                        if not chunk:
                            break
                        file_size += len(chunk)
                        total_size += len(chunk)
                        if file_size > specification["maximum"]:
                            raise ValueError(
                                "单个上传文件不能超过 {} MB".format(
                                    specification["maximum"] // 1024 // 1024
                                )
                            )
                        if total_size > HTTP_UPLOAD_MAXIMUM_SIZE:
                            raise ValueError("本次上传内容超过服务器限制")
                        output.write(chunk)
                file_paths.append(target)
            if not file_paths:
                raise ValueError("没有收到可用文件")
            if not specification["directory"] and len(file_paths) != 1:
                raise ValueError("该上传类型只能包含一个文件")
            source_path = file_paths[0]
            if specification["directory"]:
                manifests = [
                    item for item in upload_directory.rglob("plugin.json")
                    if item.is_file()
                ]
                if len(manifests) != 1:
                    raise ValueError("上传目录必须且只能包含一个 plugin.json")
                source_path = manifests[0].parent
            record = {
                "kind": kind,
                "directory": upload_directory,
                "path": source_path,
                "fileName": file_paths[0].name,
                "size": total_size,
                "expires": time.monotonic() + HTTP_UPLOAD_TTL_SECONDS,
            }
            with self._upload_lock:
                self._uploads[upload_id] = record
            return web.json_response({
                "ok": True,
                "data": {
                    "uploadId": upload_id,
                    "kind": kind,
                    "fileName": record["fileName"],
                    "size": total_size,
                },
            })
        except Exception as error:
            shutil.rmtree(upload_directory, ignore_errors=True)
            LOGGER.exception("接收 HTTP 文件上传失败")
            return web.json_response(
                {"ok": False, "message": str(error) or "文件上传失败"},
                status=400,
            )

    def _resolve_http_upload(self, action, payload):
        """把 uploadId 解析成服务端临时路径，禁止客户端传入任意本地路径。"""
        expected_kind = HTTP_UPLOAD_ACTION_KINDS.get(action)
        upload_id = str(payload.get("uploadId") or "").strip()
        if expected_kind is None:
            return dict(payload), HTTP_UNSUPPORTED_ACTIONS.get(action), None
        if not upload_id:
            return None, "请先使用浏览器选择文件", None
        with self._upload_lock:
            record = self._uploads.get(upload_id)
        if record is None or record["expires"] <= time.monotonic():
            if record is not None:
                self._cleanup_uploads()
            return None, "文件上传已过期，请重新选择文件", upload_id
        if record["kind"] != expected_kind:
            return None, "上传文件类型与当前操作不匹配", upload_id
        prepared = dict(payload)
        prepared["sourcePath"] = str(record["path"])
        prepared.pop("packagePath", None)
        return prepared, None, upload_id

    def _finalize_http_upload(self, action, result, upload_id):
        """清理已消费的上传，并隐藏服务端本地路径。"""
        if not upload_id or not isinstance(result, dict):
            return result
        data = result.get("data")
        if isinstance(data, dict):
            if action in ("data.import", "data.importDirectory"):
                data.pop("sourcePath", None)
            if action == "device.firmware.select":
                package = data.get("package")
                if isinstance(package, dict):
                    package.pop("path", None)
                    package["uploadId"] = upload_id
            if action == "device.sdk.select":
                image = data.get("image")
                if isinstance(image, dict):
                    image["uploadId"] = upload_id
        if result.get("ok") and not (
            isinstance(data, dict) and data.get("requiresOverwrite")
        ) and action in (
            "data.import",
            "data.importDirectory",
            "style.upload",
            "device.firmware.updateLocal",
            "device.sdk.flash",
        ):
            with self._upload_lock:
                record = self._uploads.pop(upload_id, None)
            if record is not None:
                shutil.rmtree(record["directory"], ignore_errors=True)
        return result

    async def _invoke_bridge(self, action, payload):
        """统一处理 HTTP/WebSocket action 的上传路径解析和桥接调用。"""
        prepared, unsupported, upload_id = self._resolve_http_upload(action, payload)
        if unsupported:
            return {"ok": False, "message": unsupported}
        result = await asyncio.to_thread(self.bridge.invoke, action, prepared)
        return self._finalize_http_upload(action, result, upload_id)

    async def _http_invoke(self, request):
        """通过带鉴权 Header 的 HTTP 请求代理一次 invoke 调用。"""
        if not self._header_auth_matches(request):
            raise web.HTTPUnauthorized(text="鉴权失败")
        try:
            payload = await request.json()
            action = str(payload.get("action") or "")
            if not action:
                raise ValueError("缺少 action")
            result = await self._invoke_bridge(action, payload.get("payload") or {})
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
                result = await self._invoke_bridge(action, payload.get("payload") or {})
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
        application = web.Application(client_max_size=HTTP_UPLOAD_MAXIMUM_SIZE)
        application.router.add_get("/api/health", self._health)
        application.router.add_get("/api/runtime", self._runtime)
        application.router.add_post("/api/uploads/{kind}", self._upload)
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
            if self._startup_error is None:
                self._upload_cleanup_stop.clear()
                self._upload_cleanup_thread = threading.Thread(
                    target=self._upload_cleanup_loop,
                    name="omniwatch-http-upload-cleanup",
                    daemon=True,
                )
                self._upload_cleanup_thread.start()
            self._started.set()
        if self._startup_error is None:
            loop.run_forever()
        if self._runner is not None:
            loop.run_until_complete(self._runner.cleanup())
        self._upload_cleanup_stop.set()
        cleanup_thread = self._upload_cleanup_thread
        if cleanup_thread is not None and cleanup_thread.is_alive():
            cleanup_thread.join(timeout=2)
        self._upload_cleanup_thread = None
        loop.close()

    def start(self):
        """启动服务线程并同步报告端口占用等初始化错误。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._upload_root.mkdir(parents=True, exist_ok=True)
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
        self._upload_cleanup_stop.set()
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._cleanup_uploads(force=True)
        shutil.rmtree(self._upload_root, ignore_errors=True)
        self._thread = None
        self._loop = None


def __getattr__(name):
    """延迟提供历史 Linux 桥接入口，避免公共 HTTP 服务依赖平台实现。"""
    if name == "LinuxInvokeBridge":
        from desktop.linux.bridge import LinuxInvokeBridge
        return LinuxInvokeBridge
    raise AttributeError(name)
