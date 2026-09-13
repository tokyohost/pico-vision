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


class LinuxInvokeBridge:
    """为 Linux 无桌面服务提供与桌面端一致的 HTTP 调用协议。"""

    def __init__(self, service):
        """保存监控服务引用，并初始化跨线程状态。"""
        self._service = service
        self._settings_lock = threading.RLock()
        self._selected_firmware_path = None
        self._selected_sdk_path = None
        self._market_lock = threading.Lock()
        self._market_state = {
            "busy": False,
            "status": "idle",
            "progress": 0,
            "message": "",
            "logs": [],
            "result": None,
        }
        self._update_states = {
            category: {
                "busy": False,
                "status": "idle",
                "message": "",
                "progress": 0,
                "logs": [],
            }
            for category in ("firmware", "sdk", "application")
        }
        self._http_server = None

    def attach_http_server(self, server):
        """绑定 HTTP 服务，使首屏可以显示当前服务端口和鉴权配置。"""
        self._http_server = server

    def _device_status(self, payload=None):
        """返回 Linux 服务当前设备的完整连接与版本状态。"""
        del payload
        client = self._service.client
        port = getattr(client, "port_name", None)
        websocket = isinstance(port, str) and port.lower().startswith(("ws://", "wss://"))
        width = getattr(client, "screen_width", None)
        height = getattr(client, "screen_height", None)
        screen_resolution = "{}x{}".format(width, height) if width and height else ""
        network_status = getattr(client, "net_status", None) or {}
        sdk_update_info = getattr(client, "sdk_update_info", None) or {}
        return {
            "connected": bool(client.is_connected),
            "port": port,
            "address": port,
            "wifi_address": network_status.get("ip") or network_status.get("address"),
            "transport": "WebSocket" if websocket else "USB CDC",
            "board_model": getattr(client, "board_model", None),
            "device_id": getattr(client, "device_id", None),
            "lcd_device_type": getattr(client, "lcd_device_type", None),
            "screen_color_profile": getattr(client, "screen_color_profile", None),
            "screen_resolution": screen_resolution,
            "firmware_version": getattr(client, "firmware_version", None),
            "sdk_version": getattr(client, "sdk_version", None),
            "wifi_supported": bool(network_status.get("wifi_enabled")),
            "sdk_update_supported": bool(sdk_update_info.get("supported")),
        }

    def _style_catalog(self):
        """返回包含内置样式和设备自定义样式的规范化目录。"""
        from win.settings import normalize_style_catalog

        return normalize_style_catalog(getattr(self._service.client, "styles", []))

    def _settings_snapshot(self):
        """把 Linux 命令行参数转换为 Vue 设置页使用的字段结构。"""
        arguments = self._service.arguments
        settings = {
            name: getattr(arguments, name, default)
            for name, default in {
                "port": "",
                "websocket_url": "",
                "force_usb_cdc": False,
                "websocket_client_name": "Monitor",
                "websocket_client_id": "",
                "ping_target": "",
                "interval": 0.5,
                "json_chunk_size": 4096,
                "adaptive_transmit": True,
                "reconnect_interval": 3.0,
                "serial_probe_interval": 3.0,
                "wifi_discovery_strategy": "announcement",
                "wifi_announcement_port": 37856,
                "wifi_announcement_group": "239.255.77.77",
                "wifi_announcement_timeout": 3.0,
                "lan_probe_port": 8765,
                "lan_probe_path": "/pv1",
                "lan_probe_timeout": 0.3,
                "lan_probe_max_workers": 256,
                "collection_task_intervals": {},
                "custom_data_configs": {},
                "custom_data_enabled": {},
                "collection_task_logs": True,
                "screen_rotation": 0,
                "lcd_brightness": 100,
                "network_unit": "MB",
                "lcd_style": "default",
                "idle_enabled": True,
                "idle_style": "idle",
                "idle_timeout": 30,
                "qbittorrent_enabled": False,
                "qbittorrent_address": "",
                "qbittorrent_username": "",
                "qbittorrent_password": "",
                "qbittorrent_interval": 2.0,
                "market_url": "https://omni.mzlblog.com",
                "dev": False,
            }.items()
        }
        settings["market_url"] = (
            str(settings.get("market_url") or "").strip()
            or "https://omni.mzlblog.com"
        )
        settings["styles"] = self._style_catalog()
        server = self._http_server
        if server is not None:
            settings.update({
                "http_enabled": True,
                "http_host": server.host,
                "http_port": server.port,
                "http_auth": server.auth,
            })
        return settings

    def _bootstrap(self, payload=None):
        """构造现有 Vue 首屏所需的 Linux 兼容数据。"""
        del payload
        import custom_data

        from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
        from collectTask import system_task_defaults, system_task_zh_names

        settings = self._settings_snapshot()
        qq_group_qr_path = Path(__file__).resolve().parent / "assert" / "qqgroup.png"
        qq_group_qr_data_url = ""
        if qq_group_qr_path.is_file():
            qq_group_qr_data_url = "data:image/png;base64," + base64.b64encode(
                qq_group_qr_path.read_bytes()
            ).decode("ascii")
        return {
            "applicationName": "OmniWatch",
            "version": MONITOR_VERSION,
            "settings": settings,
            "styles": self._style_catalog(),
            "taskNames": system_task_zh_names(),
            "defaultTasks": list(system_task_defaults()),
            "customDataPanels": custom_data.custom_data_panels(),
            "device": self._device_status(),
            "dataDirectory": str(custom_data.get_data_root()),
            "about": {
                "author": "tokyohost",
                "wechat": "hi2024FL",
                "repository": GITHUB_REPOSITORY,
                "qrDataUrl": "",
                "qqGroup": "1109488330",
                "qqGroupQrDataUrl": qq_group_qr_data_url,
            },
        }

    @staticmethod
    def _wait_result(result_queue, timeout, action):
        """等待设备主循环返回指定控制动作的结果。"""
        try:
            result = result_queue.get(timeout=timeout)
        except queue.Empty as error:
            raise RuntimeError(
                "等待设备操作超时，请确认 Monitor 主循环仍在运行：{}".format(action)
            ) from error
        if result.get("status") != "ok":
            raise RuntimeError(result.get("message") or "设备操作失败")
        return result

    @staticmethod
    def _response_data(result):
        """提取设备命令响应中的 data 对象。"""
        data = result.get("data") if isinstance(result, dict) else None
        return data if isinstance(data, dict) else {}

    def _market_origin(self):
        """提取当前插件市场地址的同源信息。"""
        configured = str(
            getattr(self._service.arguments, "market_url", "") or ""
        ).strip()
        parsed = urlsplit(configured)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise RuntimeError("尚未配置有效的插件市场地址")
        default_port = 443 if parsed.scheme == "https" else 80
        return parsed.scheme, parsed.hostname.lower(), parsed.port or default_port

    def _validate_market_download_url(self, download_url):
        """限制插件下载地址必须与配置的市场地址同源。"""
        parsed = urlsplit(str(download_url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("插件下载地址必须使用 http:// 或 https://")
        default_port = 443 if parsed.scheme == "https" else 80
        origin = parsed.scheme, parsed.hostname.lower(), parsed.port or default_port
        if origin != self._market_origin():
            raise ValueError("插件下载地址与当前市场不同源，已拒绝安装")
        return str(download_url).strip()

    def _set_market_state(self, status, progress=None, message="", result=None):
        """更新 Linux 插件市场后台安装状态。"""
        with self._market_lock:
            self._market_state["status"] = str(status)
            self._market_state["busy"] = status == "running"
            if progress is not None:
                self._market_state["progress"] = max(0, min(100, int(progress)))
            self._market_state["message"] = str(message or "")
            if message:
                self._market_state["logs"].append(str(message))
                del self._market_state["logs"][:-1000]
            if result is not None:
                self._market_state["result"] = result

    def _download_market_package(self, download_url, target_path):
        """流式下载同源插件 ZIP，并限制最大体积。"""
        from build_info import MONITOR_VERSION

        request = urllib.request.Request(
            download_url,
            headers={
                "Accept": "application/zip, application/octet-stream",
                "User-Agent": "OmniWatch-Monitor/{}".format(MONITOR_VERSION),
            },
        )

        bridge = self

        class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
            """限制市场下载请求不能通过重定向跳出同源。"""

            def redirect_request(self, request, file_pointer, code, message, headers, new_url):
                """校验重定向目标后继续标准 HTTP 重定向。"""
                bridge._validate_market_download_url(new_url)
                return super().redirect_request(
                    request, file_pointer, code, message, headers, new_url
                )

        opener = urllib.request.build_opener(SameOriginRedirectHandler())
        with opener.open(request, timeout=30) as response:
            bridge._validate_market_download_url(response.geturl())
            total = int(response.headers.get("Content-Length") or 0)
            if total > 20 * 1024 * 1024:
                raise ValueError("插件包超过 20 MB 限制")
            received = 0
            with Path(target_path).open("wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > 20 * 1024 * 1024:
                        raise ValueError("插件包超过 20 MB 限制")
                    output.write(chunk)
                    if total:
                        bridge._set_market_state(
                            "running",
                            10 + int(received * 55 / total),
                            "正在下载插件包：{}%".format(
                                min(100, int(received * 100 / total))
                            ),
                        )
            if received == 0:
                raise ValueError("市场返回了空插件包")

    def _run_market_install(self, download_url, plugin_name, plugin_type):
        """在后台下载、校验并安装 Linux 市场资源。"""
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="omniwatch-market-", suffix=".zip"
        )
        os.close(descriptor)
        package_path = Path(temporary_name)
        try:
            self._set_market_state("running", 8, "开始下载“{}”".format(plugin_name))
            self._download_market_package(download_url, package_path)
            self._set_market_state("running", 70, "下载完成，正在校验 ZIP 插件包")
            if not zipfile.is_zipfile(package_path):
                raise ValueError("下载内容不是有效的 ZIP 插件包")
            if plugin_type == "style":
                if not self._device_status().get("connected"):
                    raise RuntimeError("请先连接设备，连接成功后即可安装 Style 界面样式")
                result = self._upload_style_source(
                    package_path,
                    {"overwrite": True, "existingNames": []},
                )
                result["name"] = result.get("filename", plugin_name)
                result["chineseName"] = plugin_name
            else:
                result = self._import_custom_data_source(
                    package_path,
                    {"overwrite": True},
                )
            self._set_market_state(
                "success",
                100,
                "插件“{}”安装完成".format(result.get("chineseName") or plugin_name),
                result=result,
            )
        except Exception as error:
            self._set_market_state(
                "error",
                None,
                "插件“{}”安装失败：{}".format(plugin_name, error),
            )
            LOGGER.exception("Linux HTTP 插件市场安装失败")
        finally:
            package_path.unlink(missing_ok=True)

    def _market_install(self, payload):
        """校验市场安装请求并启动唯一后台任务。"""
        download_url = self._validate_market_download_url(payload.get("downloadUrl"))
        plugin_name = str(payload.get("pluginName") or "未命名插件").strip()[:120]
        plugin_type = str(payload.get("pluginType") or "plugin").strip()
        if plugin_type not in ("plugin", "style"):
            raise ValueError("市场资源类型必须是 plugin 或 style")
        if plugin_type == "style" and not self._device_status().get("connected"):
            raise RuntimeError("请先连接设备，连接成功后即可安装 Style 界面样式")
        with self._market_lock:
            if self._market_state["busy"]:
                raise RuntimeError("已有插件正在下载安装，请稍候")
            self._market_state.update({
                "busy": True,
                "status": "running",
                "progress": 2,
                "message": "正在准备下载安装",
                "logs": ["正在准备下载安装"],
                "result": None,
            })
        threading.Thread(
            target=self._run_market_install,
            args=(download_url, plugin_name, plugin_type),
            name="Linux HTTP 插件市场安装",
            daemon=True,
        ).start()
        return {"started": True}

    def _market_install_status(self, payload):
        """返回 Linux 插件市场安装进度和最终结果。"""
        del payload
        with self._market_lock:
            return {
                "busy": self._market_state["busy"],
                "status": self._market_state["status"],
                "progress": self._market_state["progress"],
                "message": self._market_state["message"],
                "logs": "\n".join(self._market_state["logs"]),
                "result": self._market_state["result"],
            }

    def _save_linux_settings(self):
        """将运行时配置写回 YAML 文件；没有配置文件时仅保留本次运行结果。"""
        config_path = str(getattr(self._service.arguments, "config", "") or "").strip()
        if not config_path:
            return False
        path = Path(config_path)
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8-sig")
        first_content_line = next(
            (
                line.strip()
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ),
            "",
        )
        if first_content_line.startswith("PICO_MONITOR_"):
            raise RuntimeError("旧版 EnvironmentFile 不支持从 HTTP 页面写回配置")
        try:
            import yaml

            document = yaml.safe_load(text) or {}
        except ImportError as error:
            raise RuntimeError("保存 Linux 配置需要安装 PyYAML") from error
        if not isinstance(document, dict):
            raise RuntimeError("Linux YAML 配置根节点必须是对象")
        settings = self._settings_snapshot()
        field_map = {
            "port": ("serial", "port"),
            "websocket_url": ("network", "websocket_url"),
            "force_usb_cdc": ("network", "force_usb_cdc"),
            "websocket_client_name": ("network", "websocket_client_name"),
            "websocket_client_id": ("network", "websocket_client_id"),
            "wifi_discovery_strategy": ("network", "discovery_strategy"),
            "wifi_announcement_port": ("network", "announcement_port"),
            "wifi_announcement_group": ("network", "announcement_group"),
            "wifi_announcement_timeout": ("network", "announcement_timeout"),
            "ping_target": ("network", "ping_target"),
            "interval": ("monitor", "interval"),
            "json_chunk_size": ("monitor", "json_chunk_size"),
            "adaptive_transmit": ("monitor", "adaptive_transmit"),
            "reconnect_interval": ("monitor", "reconnect_interval"),
            "serial_probe_interval": ("serial", "probe_interval"),
            "collection_task_intervals": ("collection_tasks", "intervals"),
            "collection_task_logs": ("collection_tasks", "logs_enabled"),
            "custom_data_configs": ("custom_data", "configs"),
            "custom_data_enabled": ("custom_data", "enabled"),
            "screen_rotation": ("screen", "rotation"),
            "lcd_brightness": ("screen", "lcd_brightness"),
            "network_unit": ("screen", "unit"),
            "lcd_style": ("screen", "lcd_style"),
            "idle_enabled": ("screen", "idle_enabled"),
            "idle_style": ("screen", "idle_style"),
            "idle_timeout": ("screen", "idle_timeout"),
            "market_url": ("market", "url"),
            "qbittorrent_enabled": ("qbittorrent", "enabled"),
            "qbittorrent_address": ("qbittorrent", "address"),
            "qbittorrent_username": ("qbittorrent", "username"),
            "qbittorrent_password": ("qbittorrent", "password"),
            "qbittorrent_interval": ("qbittorrent", "interval"),
        }
        for name, location in field_map.items():
            section = document.setdefault(location[0], {})
            if not isinstance(section, dict):
                raise RuntimeError("Linux 配置节点不是对象：{}".format(location[0]))
            section[location[1]] = settings.get(name)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(path)
        return True

    def _save_settings(self, payload):
        """校验并热更新 Linux 运行配置，同时尽量写回 YAML 文件。"""
        incoming = payload.get("settings")
        if not isinstance(incoming, dict):
            raise ValueError("缺少有效配置")
        with self._settings_lock:
            current = self._settings_snapshot()
            updated = dict(current)
            updated.update({key: value for key, value in incoming.items() if key in current})
            market_url = str(updated.get("market_url") or "").strip()
            parsed = urlsplit(market_url)
            if market_url and (
                parsed.scheme not in ("http", "https") or not parsed.netloc
            ):
                raise ValueError("插件市场地址必须是有效的 http:// 或 https:// 地址")
            updated["market_url"] = market_url
            runtime_fields = {
                name: updated[name]
                for name in (
                    "port", "websocket_url", "force_usb_cdc", "websocket_client_name",
                    "websocket_client_id", "wifi_discovery_strategy", "wifi_announcement_port",
                    "wifi_announcement_group", "wifi_announcement_timeout", "ping_target",
                    "interval", "json_chunk_size", "adaptive_transmit", "reconnect_interval", "serial_probe_interval",
                    "lan_probe_port", "lan_probe_path", "lan_probe_timeout", "lan_probe_max_workers",
                    "collection_task_intervals", "custom_data_configs", "custom_data_enabled",
                    "collection_task_logs", "screen_rotation", "lcd_brightness", "network_unit",
                    "lcd_style", "idle_enabled", "idle_style", "idle_timeout", "qbittorrent_enabled",
                    "qbittorrent_address", "qbittorrent_username", "qbittorrent_password",
                    "qbittorrent_interval", "dev",
                )
                if name in updated
            }
            self._service.apply_runtime_config(runtime_fields)
            self._service.arguments.market_url = market_url
            persisted = self._save_linux_settings()
        return {"saved": True, "persisted": persisted}

    def _verify_qbittorrent(self, payload):
        """验证 Linux 主机上的 qBittorrent WebUI 账号。"""
        from qbittorrent_monitor import QbittorrentApiClient

        client = QbittorrentApiClient(
            str(payload.get("address") or "").strip(),
            str(payload.get("username") or "").strip(),
            str(payload.get("password") or ""),
        )
        client.login()
        return {"verified": True}

    def _custom_data_list(self, payload):
        """返回 Linux 主机已安装自定义数据插件及其运行状态。"""
        del payload
        manager = self._service.custom_data_manager
        states, errors = manager.list_items()
        items = []
        for state in states:
            definition = state.definition
            preview_data_url = ""
            if definition.preview_path and definition.preview_path.is_file():
                mime_type = mimetypes.guess_type(definition.preview_path.name)[0] or "image/png"
                preview_data_url = "data:{};base64,{}".format(
                    mime_type,
                    base64.b64encode(definition.preview_path.read_bytes()).decode("ascii"),
                )
            items.append({
                "name": definition.name,
                "key": definition.key,
                "version": definition.version,
                "taskName": definition.task_name,
                "chineseName": definition.zh_name,
                "interval": definition.interval,
                "boundStyle": definition.style_filename,
                "hasDetail": bool(definition.detail_path),
                "detailFilename": definition.detail_filename,
                "previewFilename": definition.preview_filename,
                "previewDataUrl": preview_data_url,
                "path": str(definition.plugin_directory),
                "environment": manager.environment_status(definition),
                "enabled": bool(self._service.arguments.custom_data_enabled.get(
                    definition.name, state.runtime_enabled
                )),
                "hasUninstall": definition.has_uninstall,
                "hasActions": bool(definition.actions),
                "error": state.error or state.environment_error,
            })
        return {
            "items": items,
            "errors": [{"path": str(path), "message": str(error)} for path, error in errors.items()],
        }

    def _persist_custom_data_settings(self):
        """同步自定义插件配置到运行参数和 Linux 配置文件。"""
        self._service.update_custom_data_runtime_settings()
        self._save_linux_settings()

    def _import_custom_data_source(self, path, payload):
        """导入已上传的 ZIP 或目录插件，并返回可覆盖冲突信息。"""
        import custom_data

        manager = self._service.custom_data_manager
        try:
            definition = manager.import_plugin(path, bool(payload.get("overwrite")))
        except custom_data.CustomDataDuplicateError as error:
            return {
                "requiresOverwrite": True,
                "message": str(error),
                "sourcePath": str(path),
                "conflicts": [
                    {"name": item.zh_name, "key": item.key, "taskName": item.task_name}
                    for item in error.conflicts
                ],
            }
        enabled = dict(custom_data.normalize_plugin_enabled(
            getattr(self._service.arguments, "custom_data_enabled", {})
        ))
        enabled[definition.name] = False
        self._service.arguments.custom_data_enabled = enabled
        self._service.arguments.custom_data_configs = custom_data.normalize_plugin_configs(
            getattr(self._service.arguments, "custom_data_configs", {})
        )
        self._persist_custom_data_settings()
        return {"name": definition.name, "chineseName": definition.zh_name}

    def _custom_data_import(self, payload):
        """导入浏览器上传的 ZIP 数据插件。"""
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            raise ValueError("请先从浏览器选择插件 ZIP")
        return self._import_custom_data_source(path, payload)

    def _custom_data_import_directory(self, payload):
        """导入浏览器按目录上传的自定义数据插件。"""
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            raise ValueError("请先从浏览器选择插件目录")
        return self._import_custom_data_source(path, payload)

    def _custom_data_set_enabled(self, payload):
        """更新 Linux 自定义数据插件启用状态并热更新采集调度。"""
        import custom_data

        name = str(payload.get("name") or "").strip()
        definitions = {item.name: item for item in self._service.custom_data_manager.list_definitions()}
        if name not in definitions:
            raise ValueError("插件不存在或尚未加载")
        enabled = dict(custom_data.normalize_plugin_enabled(
            getattr(self._service.arguments, "custom_data_enabled", {})
        ))
        enabled[name] = bool(payload.get("enabled"))
        self._service.arguments.custom_data_enabled = enabled
        self._service.custom_data_manager.set_plugin_enabled(name, enabled[name])
        self._persist_custom_data_settings()
        return {"name": name, "enabled": enabled[name]}

    def _custom_data_activate(self, payload):
        """兼容旧页面的激活动作，并转换为持久启用状态。"""
        result = self._custom_data_set_enabled({
            "name": payload.get("name"),
            "enabled": True,
        })
        return {"activated": True, "applied": True, **result}

    def _custom_data_install_dependencies(self, payload):
        """为 Linux 数据插件创建独立环境并安装依赖。"""
        name = str(payload.get("name") or "").strip()
        logs = []
        result = self._service.custom_data_manager.install_dependencies(
            name,
            lambda message: logs.append(str(message)),
        )
        return {"status": result, "output": "\n".join(logs)}

    def _custom_data_test(self, payload):
        """测试运行一个 Linux 自定义数据插件。"""
        return {"output": self._service.custom_data_manager.test_plugin(
            str(payload.get("name") or "")
        )}

    def _custom_data_detail(self, payload):
        """读取 Linux 插件绑定的 UTF-8 HTML 简介。"""
        name = str(payload.get("name") or "").strip()
        definition = next(
            (item for item in self._service.custom_data_manager.list_definitions() if item.name == name),
            None,
        )
        if definition is None or not definition.detail_path:
            raise ValueError("插件不存在或没有绑定简介 HTML")
        return {
            "title": "{} · 插件简介".format(definition.zh_name),
            "content": definition.detail_path.read_text(encoding="utf-8-sig"),
        }

    def _custom_data_invoke_action(self, payload):
        """调用 Linux 插件公开动作并返回经过校验的配置补丁。"""
        return self._service.custom_data_manager.invoke_action(
            str(payload.get("name") or "").strip(),
            str(payload.get("action") or "").strip(),
            payload.get("config") if isinstance(payload.get("config"), dict) else {},
        )

    def _custom_data_delete(self, payload):
        """执行 Linux 插件卸载钩子并删除插件目录及其环境。"""
        import custom_data

        path = str(payload.get("path") or "").strip()
        definitions = {
            str(item.plugin_directory.resolve()): item
            for item in self._service.custom_data_manager.list_definitions()
        }
        definition = definitions.get(str(Path(path).resolve()))
        if definition is None:
            raise ValueError("插件不存在或路径不属于 customData 目录")
        enabled = dict(getattr(self._service.arguments, "custom_data_enabled", {}) or {})
        enabled[definition.name] = False
        self._service.arguments.custom_data_enabled = enabled
        self._service.custom_data_manager.set_plugin_enabled(definition.name, False)
        configs = dict(getattr(self._service.arguments, "custom_data_configs", {}) or {})
        self._service.custom_data_manager.delete_plugin(path, configs.get(definition.name, {}))
        enabled.pop(definition.name, None)
        configs.pop(definition.name, None)
        self._service.arguments.custom_data_enabled = custom_data.normalize_plugin_enabled(enabled)
        self._service.arguments.custom_data_configs = custom_data.normalize_plugin_configs(configs)
        self._persist_custom_data_settings()
        return {"deleted": True}

    def _style_list(self, payload):
        """通过 Linux Monitor 主循环查询设备样式目录。"""
        del payload
        result_queue = queue.Queue()
        self._service.request_custom_style_catalog(result_queue)
        result = self._wait_result(result_queue, 15, "style.list")
        return {
            "styles": result.get("styles") or [],
            "flash": result.get("flash") or {},
            "active_style": result.get("active_style") or "",
            "catalog": self._style_catalog(),
        }

    @staticmethod
    def _style_assets(payload):
        """读取数据插件和纯样式包提供的预览图、详情页资源。"""
        del payload
        from importlib import import_module

        style_api = import_module("win.ui-web-api.style_api")
        return style_api.StyleApiMixin._style_assets({})

    @staticmethod
    def _style_package_helpers():
        """加载与 Windows 页面共用的安全样式包解析工具。"""
        from importlib import import_module

        return import_module("win.ui-web-api.style_api").StyleApiMixin

    def _upload_style_python(self, path, payload):
        """校验浏览器上传的 Python 样式并交给 Linux 设备主循环上传。"""
        from style_validator import StyleFileValidator

        validated = StyleFileValidator().validate(path)
        existing_names = set(payload.get("existingNames") or ())
        if validated.name in existing_names and not payload.get("overwrite"):
            raise FileExistsError(
                "OmniWatch 中已存在样式名 {} 和文件 {}".format(
                    validated.name, validated.filename
                )
            )
        result_queue = queue.Queue()
        self._service.request_custom_style_upload(
            {
                "filename": validated.filename,
                "style_name": validated.name,
                "content": base64.b64encode(validated.source).decode("ascii"),
                "overwrite": bool(payload.get("overwrite")),
            },
            result_queue,
        )
        result = self._wait_result(result_queue, 120, "style.upload")
        data = self._response_data(result)
        data.update({"filename": validated.filename, "styleName": validated.name})
        return data

    def _upload_style_source(self, path, payload):
        """解析 Python 样式或样式 ZIP，并保存 ZIP 的展示资源。"""
        source_path = Path(path)
        if source_path.suffix.lower() == ".py":
            return self._upload_style_python(source_path, payload)
        if source_path.suffix.lower() != ".zip":
            raise ValueError("屏幕样式仅支持 py 文件或 zip 包")
        helpers = self._style_package_helpers()
        with tempfile.TemporaryDirectory(prefix="omniwatch-style-") as temporary:
            package = helpers._extract_style_package(source_path, Path(temporary))
            result = self._upload_style_python(package["style"], payload)
            helpers._persist_style_package_assets(
                result["styleName"], package.get("detail"), package.get("preview")
            )
            return result

    def _style_upload(self, payload):
        """处理浏览器上传的 Python 样式或 ZIP 样式包。"""
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            raise ValueError("请先从浏览器选择 PY 或 ZIP 样式")
        return self._upload_style_source(path, payload)

    def _style_delete(self, payload):
        """通过 Linux Monitor 主循环删除设备自定义样式。"""
        result_queue = queue.Queue()
        self._service.request_custom_style_delete(
            {
                "style_name": str(payload.get("name") or "").strip().lower(),
                "filename": str(payload.get("filename") or "").strip(),
            },
            result_queue,
        )
        result = self._wait_result(result_queue, 30, "style.delete")
        data = self._response_data(result)
        data["catalog"] = self._style_catalog()
        return data

    def _custom_data_sync_style(self, payload):
        """将 Linux 数据插件绑定的样式上传到当前设备。"""
        name = str(payload.get("name") or "").strip()
        definition = next(
            (item for item in self._service.custom_data_manager.list_definitions() if item.name == name),
            None,
        )
        if definition is None or not definition.bind_style or not definition.style_path:
            raise ValueError("该插件没有绑定可同步的屏幕样式")
        existing_names = {
            str(item.get("name") or "")
            for item in self._style_catalog()
            if isinstance(item, dict) and item.get("type") == "custom"
        }
        result = self._upload_style_python(
            definition.style_path,
            {"existingNames": existing_names, "overwrite": bool(payload.get("overwrite"))},
        )
        result["catalog"] = self._style_catalog()
        return result

    def _custom_data_sync_style_progress(self, payload):
        """返回 Linux 样式上传的兼容进度结构。"""
        del payload
        return {"active": False, "progresses": []}

    def _wifi_list(self, payload):
        """通过 Linux Monitor 主循环扫描设备附近 Wi-Fi。"""
        del payload
        result_queue = queue.Queue()
        self._service.request_wifi_list(result_queue)
        result = self._wait_result(result_queue, 30, "wifi.list")
        from win.ui.wifi_window import merge_wifi_networks, wifi_security_label, wifi_state_label

        data = self._response_data(result)
        networks = merge_wifi_networks(data.get("networks"), data.get("wifi"))
        for network in networks:
            network["state_label"] = wifi_state_label(network)
            network["security_label"] = wifi_security_label(network.get("security"))
        return {"action": "list", "networks": networks, "wifi": data.get("wifi") or {}}

    def _wifi_connect(self, payload):
        """通过 Linux Monitor 主循环连接设备 Wi-Fi。"""
        result_queue = queue.Queue()
        self._service.request_wifi_connect(payload, result_queue)
        return self._response_data(self._wait_result(result_queue, 30, "wifi.connect"))

    def _wifi_forget(self, payload):
        """通过 Linux Monitor 主循环删除设备已保存 Wi-Fi。"""
        result_queue = queue.Queue()
        self._service.request_wifi_forget(payload, result_queue)
        return self._response_data(self._wait_result(result_queue, 20, "wifi.forget"))

    def _websocket_list(self, payload):
        """通过 Linux Monitor 主循环读取 WebSocket 客户端策略。"""
        del payload
        result_queue = queue.Queue()
        self._service.request_websocket_client_list(result_queue)
        data = self._response_data(self._wait_result(result_queue, 20, "websocket.list"))
        clients = []
        for client in data.get("clients", ()):
            if not isinstance(client, dict) or not client.get("id"):
                continue
            normalized = dict(client)
            normalized["enabled"] = bool(client.get("enabled", True))
            normalized["active"] = bool(client.get("active", False))
            normalized["priority"] = int(client.get("priority", 0))
            normalized["connections"] = int(client.get("connections", 0))
            clients.append(normalized)
        return {"action": "list", "clients": clients}

    def _websocket_update(self, payload):
        """通过 Linux Monitor 主循环更新 WebSocket 客户端策略。"""
        result_queue = queue.Queue()
        self._service.request_websocket_client_update(payload, result_queue)
        return self._response_data(
            self._wait_result(result_queue, 20, "websocket.update")
        )

    def _device_probe(self, payload):
        """请求 Linux Monitor 立即执行一次设备探测。"""
        del payload
        self._service.request_active_probe()
        return {"device": self._device_status(), "log": "已请求主循环立即探测设备"}

    def _device_screenshot(self, payload):
        """通过 Linux Monitor 主循环保存设备截图。"""
        del payload
        result_queue = queue.Queue()
        self._service.request_screenshot(result_queue)
        result = self._wait_result(result_queue, 40, "device.screenshot")
        return result.get("data") or {"requested": True}

    def _device_reboot(self, payload):
        """通过 Linux Monitor 主循环发送设备重启命令。"""
        del payload
        result_queue = queue.Queue()
        self._service.request_device_control("device.reboot", result_queue=result_queue)
        return self._response_data(self._wait_result(result_queue, 40, "device.reboot"))

    def _firmware_ports(self, payload):
        """返回 Linux 主机可用于固件操作的串口清单。"""
        del payload
        from serial.tools import list_ports

        ports = []
        for item in list_ports.comports():
            device = str(getattr(item, "device", "") or "").strip()
            if device:
                ports.append({"device": device, "label": "{} - {}".format(
                    device, str(getattr(item, "description", "未知设备") or "未知设备")
                )})
        current = str(getattr(self._service.client, "port_name", "") or "")
        return {"ports": ports, "recommendedPort": current if current else (ports[0]["device"] if ports else "")}

    def _firmware_select(self, payload):
        """校验浏览器上传的 Linux 固件全量包。"""
        from pico_upgrade import PicoFirmwareArchive

        path = Path(str(payload.get("sourcePath") or "").strip())
        if path.suffix.lower() != ".zip":
            raise ValueError("请选择 ZIP 格式的设备固件全量包")
        package = PicoFirmwareArchive(path)
        try:
            file_count = len(package.files)
        finally:
            package.close()
        self._selected_firmware_path = path
        return {
            "cancelled": False,
            "package": {"path": str(path), "name": path.name, "fileCount": file_count},
        }

    def _firmware_update(self, payload):
        """安排 Linux 主循环安装已上传的 Pico 固件包。"""
        path = str(payload.get("sourcePath") or self._selected_firmware_path or "").strip()
        if not path:
            raise ValueError("请先选择设备固件全量包")
        if not self._service.client.is_connected:
            raise RuntimeError("设备未连接，无法更新固件")
        current_port = str(getattr(self._service.client, "port_name", "") or "")
        selected_port = str(payload.get("port") or "").strip()
        if current_port.lower().startswith(("ws://", "wss://")):
            raise RuntimeError("Linux 固件更新需要当前设备使用 USB CDC 连接")
        if selected_port and current_port and selected_port != current_port:
            raise RuntimeError("所选固件串口不是当前 Monitor 已连接的设备串口")
        state = self._update_states["firmware"]
        if state["busy"]:
            raise RuntimeError("已有固件更新任务正在执行，请稍候")
        state.update({
            "busy": True,
            "status": "running",
            "progress": 5,
            "message": "正在通过 Monitor 主循环更新固件",
            "logs": [],
        })
        result_queue = queue.Queue()
        self._service.request_device_control(
            "device.firmware.update",
            {"path": path, "port": str(payload.get("port") or "")},
            result_queue,
        )
        try:
            self._wait_result(result_queue, 180, "device.firmware.updateLocal")
        except Exception as error:
            state.update({"busy": False, "status": "error", "message": str(error)})
            raise
        state.update({
            "busy": False,
            "status": "success",
            "progress": 100,
            "message": "设备固件更新完成",
        })
        return {
            "started": True,
            "packageName": Path(path).name,
            "port": selected_port or current_port,
            "force": bool(payload.get("force")),
        }

    def _sdk_select(self, payload):
        """校验浏览器上传的 ESP32-S3 SDK 镜像。"""
        from sdk_flash import inspect_sdk_image

        path = Path(str(payload.get("sourcePath") or "").strip())
        information = inspect_sdk_image(path)
        self._selected_sdk_path = path
        return {
            "cancelled": False,
            "image": {
                "name": information.path.name,
                "sdkVersion": information.sdk_version,
                "size": information.size,
                "sha256": information.sha256,
            },
        }

    def _sdk_ports(self, payload):
        """返回 Linux 主机可供 ESP32-S3 强刷使用的串口清单。"""
        return self._firmware_ports(payload)

    def _sdk_status(self, payload):
        """返回 Linux SDK 更新状态的兼容结构。"""
        del payload
        return dict(self._update_states["sdk"])

    def _sdk_flash(self, payload):
        """安排 Linux 主循环执行 ESP32-S3 SDK 镜像刷写。"""
        image_path = str(self._selected_sdk_path or "").strip()
        if not image_path:
            raise ValueError("请先选择 SDK 镜像")
        force = bool(payload.get("force"))
        port = str(payload.get("port") or "").strip()
        if not force:
            port = port or str(getattr(self._service.client, "port_name", "") or "")
        if not port:
            raise ValueError("找不到可用于 SDK 刷写的串口")
        state = self._update_states["sdk"]
        if state["busy"]:
            raise RuntimeError("已有 SDK 更新任务正在执行，请稍候")
        state.update({
            "busy": True,
            "status": "running",
            "progress": 5,
            "message": "正在准备 SDK 刷写",
            "logs": [],
        })
        result_queue = queue.Queue()
        self._service.request_device_control(
            "device.sdk.flash",
            {"path": image_path, "port": port, "force": force},
            result_queue,
        )
        try:
            result = self._wait_result(result_queue, 240, "device.sdk.flash")
        except Exception as error:
            state.update({
                "busy": False,
                "status": "error",
                "message": str(error),
            })
            raise
        state.update({
            "busy": False,
            "status": "success",
            "progress": 100,
            "message": "SDK 刷写完成",
        })
        return {
            "busy": False,
            "status": "success",
            "message": "SDK 刷写完成",
            "data": self._response_data(result),
        }

    def _update_status(self, payload):
        """返回 Linux 各类更新任务状态。"""
        category = str(payload.get("category") or "").strip()
        if category:
            if category not in self._update_states:
                raise ValueError("不支持的更新状态类别：{}".format(category))
            return self._update_state_snapshot(self._update_states[category])
        return {
            name: self._update_state_snapshot(state)
            for name, state in self._update_states.items()
        }

    @staticmethod
    def _update_state_snapshot(state):
        """复制 Linux 更新状态，并把内部日志列表转换为页面需要的文本。"""
        snapshot = dict(state)
        logs = snapshot.get("logs") or []
        snapshot["logs"] = "\n".join(logs) if isinstance(logs, list) else str(logs)
        return snapshot

    def _set_update_state(
        self, category, status, progress, message, reset_logs=False
    ):
        """更新 Linux HTTP 页任务状态，并将每个进度阶段追加到实时日志。"""
        state = self._update_states[category]
        if reset_logs:
            state["logs"] = []
        state["busy"] = status == "running"
        state["status"] = status
        if progress is not None:
            state["progress"] = max(0, min(100, int(progress)))
        state["message"] = str(message)
        if message:
            state["logs"].append(str(message))
            del state["logs"][:-1000]

    def _update_check(self, payload):
        """检查 Linux Monitor 应用 Release，设备更新继续使用专用上传入口。"""
        from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
        from monitor_update import LinuxDebUpdater

        category = str(payload.get("category") or "").strip()
        if category != "application":
            return {
                "category": category,
                "currentVersion": self._device_status().get("firmware_version") if category == "firmware" else self._device_status().get("sdk_version"),
                "latestVersion": "不适用",
                "updateAvailable": False,
                "applicable": False,
                "assetAvailable": False,
                "assetName": "",
                "notes": "Linux HTTP 页面请使用浏览器上传本地设备更新包。",
            }
        if not GITHUB_REPOSITORY or MONITOR_VERSION == "development":
            return {
                "category": category,
                "currentVersion": MONITOR_VERSION,
                "latestVersion": MONITOR_VERSION,
                "updateAvailable": False,
                "applicable": False,
                "assetAvailable": False,
                "assetName": "",
                "notes": "开发版本没有可用的 Linux Release。",
            }
        request = urllib.request.Request(
            "https://api.github.com/repos/{}/releases/latest".format(GITHUB_REPOSITORY),
            headers={"Accept": "application/vnd.github+json", "User-Agent": "OmniWatch-Monitor"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.loads(response.read().decode("utf-8"))
        latest = str(release.get("tag_name") or "").lstrip("v")
        assets = release.get("assets") or []
        try:
            architecture = LinuxDebUpdater._architecture()
            asset = LinuxDebUpdater._find_package_asset(assets, architecture)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            asset = None
        return {
            "category": category,
            "currentVersion": MONITOR_VERSION,
            "latestVersion": latest,
            "updateAvailable": bool(latest and latest != MONITOR_VERSION),
            "applicable": True,
            "assetAvailable": asset is not None,
            "assetName": asset.get("name") if asset else "",
            "notes": str(release.get("body") or ""),
        }

    def _update_install(self, payload):
        """启动由 HTTP 更新页跟踪的 Linux DEB 更新；设备包仍走上传入口。"""
        from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
        from monitor_update import LinuxDebUpdater

        category = str(payload.get("category") or "").strip()
        if category != "application":
            raise RuntimeError("Linux HTTP 页面请先上传并校验设备更新包")
        state = self._update_states[category]
        if state["busy"]:
            raise RuntimeError("已有更新任务正在执行，请稍候")
        self._set_update_state(
            category, "running", 1, "Linux 应用更新已启动，正在准备", True
        )

        def install():
            """执行 Linux DEB 更新，并把下载及安装进度持续同步到 HTTP 页面。"""
            def report_progress(message, progress):
                """接收更新器阶段回调并写入页面进度与实时日志。"""
                self._set_update_state(
                    category, "running", progress, message
                )

            try:
                updated = LinuxDebUpdater(
                    GITHUB_REPOSITORY, MONITOR_VERSION
                ).update(progress_callback=report_progress)
                message = (
                    "Linux DEB 更新已完成"
                    if updated else "OmniWatch Linux 应用已是最新版本"
                )
                self._set_update_state(
                    category, "success", 100, message
                )
            except Exception as error:
                self._set_update_state(
                    category,
                    "error",
                    None,
                    "Linux 应用更新失败：{}".format(error),
                )
                LOGGER.exception("Linux HTTP 应用更新失败")

        threading.Thread(target=install, name="Linux HTTP 应用更新", daemon=True).start()
        return {"category": category, "started": True}

    def _log_path(self):
        """返回 Linux 运行日志路径；优先采用 systemd 配置的错误日志路径。"""
        configured = str(os.getenv("PICO_MONITOR_ERROR_LOG_PATH") or "").strip()
        return Path(configured) if configured else Path(custom_data.get_data_root()) / "pico-monitor-error.log"

    def _log_read(self, payload):
        """读取 Linux 错误日志的末尾内容。"""
        maximum = min(max(int(payload.get("maximum", 300000)), 1000), 1048576)
        path = self._log_path()
        if not path.is_file():
            return {"content": ""}
        content = path.read_bytes()[-maximum:]
        return {"content": content.decode("utf-8", errors="replace")}

    def _log_clear(self, payload):
        """清空 Linux 错误日志文件。"""
        del payload
        path = self._log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return {"cleared": True}

    def _log_export(self, payload):
        """生成 Linux 日志导出文件，供 HTTP 下载接口读取。"""
        del payload
        path = Path(custom_data.get_data_root()) / "exports" / "pico-monitor-http.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._log_read({"maximum": 1048576})["content"], encoding="utf-8")
        return {"path": str(path)}

    def _registration_api_base(self):
        """从插件市场地址推导设备注册 API 地址。"""
        configured = str(getattr(self._service.arguments, "market_url", "") or "").strip()
        parsed = urlsplit(configured)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RuntimeError("请先在设置中配置有效的插件市场/服务端地址")
        path = parsed.path.rstrip("/")
        if path.endswith("/market"):
            path = path[:-len("/market")]
        if not path:
            path = "/prod-api"
        return "{}://{}{}".format(parsed.scheme, parsed.netloc, path)

    def _registration_request(self, path, method="GET", body=None):
        """调用设备注册服务并统一解析若依 JSON 响应。"""
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self._registration_api_base() + path,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            result = json.loads(error.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError("无法连接设备注册服务：{}".format(error)) from error
        if int(result.get("code", 500)) != 200:
            raise RuntimeError(result.get("msg") or "设备注册服务请求失败")
        return result

    def _registration_status(self, payload):
        """查询当前设备或指定 UUID 的注册状态。"""
        uuid = str(payload.get("uuid") or self._device_status().get("device_id") or "").strip()
        if not uuid:
            return {"registered": False, "uuid": ""}
        result = self._registration_request("/device/registration/status?" + urllib.parse.urlencode({"uuid": uuid}))
        return {"registered": bool(result.get("registered")), "uuid": uuid}

    def _registration_register(self, payload):
        """解析注册码并提交当前 Linux 设备注册信息。"""
        import base64 as base64_module

        connection = self._device_status()
        if not connection.get("connected"):
            raise RuntimeError("设备未连接，无法立即注册")
        uuid = str(connection.get("device_id") or "").strip()
        encoded = str(payload.get("registrationCode") or "").strip()
        try:
            registration = json.loads(
                base64_module.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True).decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("注册码不是有效的 Base64 JSON") from error
        if not isinstance(registration, dict) or str(registration.get("uuid") or "").strip() != uuid:
            raise ValueError("注册码绑定的 UUID 与当前设备不一致")
        result = self._registration_request(
            "/device/registration",
            method="POST",
            body={"uuid": uuid, "activationCode": registration.get("activationCode")},
        )
        return {"registered": True, "uuid": uuid, "message": result.get("msg") or "设备注册成功"}

    def invoke(self, action, payload=None):
        """执行 Linux 已支持的 action，其余动作返回明确的不支持响应。"""
        payload = payload if isinstance(payload, dict) else {}
        handlers = {
            "app.bootstrap": self._bootstrap,
            "settings.save": self._save_settings,
            "settings.verifyQbittorrent": self._verify_qbittorrent,
            "device.status": self._device_status,
            "device.probe": self._device_probe,
            "device.screenshot": self._device_screenshot,
            "device.reboot": self._device_reboot,
            "device.registration.status": self._registration_status,
            "device.registration.register": self._registration_register,
            "device.firmware.ports": self._firmware_ports,
            "device.firmware.select": self._firmware_select,
            "device.firmware.updateLocal": self._firmware_update,
            "device.sdk.ports": self._sdk_ports,
            "device.sdk.select": self._sdk_select,
            "device.sdk.flash": self._sdk_flash,
            "device.sdk.status": self._sdk_status,
            "wifi.list": self._wifi_list,
            "wifi.connect": self._wifi_connect,
            "wifi.forget": self._wifi_forget,
            "websocket.list": self._websocket_list,
            "websocket.update": self._websocket_update,
            "style.list": self._style_list,
            "style.assets": self._style_assets,
            "style.upload": self._style_upload,
            "style.delete": self._style_delete,
            "data.list": self._custom_data_list,
            "data.import": self._custom_data_import,
            "data.importDirectory": self._custom_data_import_directory,
            "data.installDependencies": self._custom_data_install_dependencies,
            "data.activate": self._custom_data_activate,
            "data.setEnabled": self._custom_data_set_enabled,
            "data.invokeAction": self._custom_data_invoke_action,
            "data.test": self._custom_data_test,
            "data.detail": self._custom_data_detail,
            "data.syncStyle": self._custom_data_sync_style,
            "data.syncStyleProgress": self._custom_data_sync_style_progress,
            "data.delete": self._custom_data_delete,
            "market.install": self._market_install,
            "market.installStatus": self._market_install_status,
            "update.check": self._update_check,
            "update.install": self._update_install,
            "update.status": self._update_status,
            "log.read": self._log_read,
            "log.clear": self._log_clear,
            "log.export": self._log_export,
            "system.openExternalUrl": lambda item: {"url": str(item.get("url") or "")},
            "system.openDataDirectory": lambda item: {"opened": False, "path": str(custom_data.get_data_root())},
        }
        handler = handlers.get(str(action))
        if handler is None:
            return {
                "ok": False,
                "message": "Linux HTTP 管理页面暂不支持此操作：{}".format(action),
            }
        try:
            return {"ok": True, "data": handler(payload)}
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
