"""Windows pywebview 窗口的创建、启动和页面导航能力。"""

import json
import logging

from ..constants import APPLICATION_NAME
from .bridge import WebViewBridge
from web_admin import HttpAdminServer


LOGGER = logging.getLogger("pico-monitor.web-ui")
WEBVIEW2_CLIENT_KEY = (
    "Software\\Microsoft\\EdgeUpdate\\Clients\\"
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
)
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
DOTNET_FRAMEWORK_FULL_KEY = (
    r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"
)
DOTNET_FRAMEWORK_462_RELEASE = 394802


class WebUiMixin:
    """把原有多个 Tk 窗口替换为单一 pywebview Vue 应用。"""

    __slots__ = ()

    @staticmethod
    def _is_usable_webview2_version(version):
        """判断注册表版本值是否表示可用的 WebView2 Runtime。"""
        return isinstance(version, str) and version.strip() not in (
            "",
            "0.0.0.0",
        )

    @classmethod
    def _get_webview2_runtime_version(cls):
        """按照 Microsoft 推荐的注册表位置读取 Evergreen Runtime 版本。"""
        import winreg

        registry_locations = (
            (winreg.HKEY_CURRENT_USER, winreg.KEY_READ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ),
        )
        for root_key, access in registry_locations:
            try:
                with winreg.OpenKey(
                    root_key,
                    WEBVIEW2_CLIENT_KEY,
                    0,
                    access,
                ) as registry_key:
                    version, _ = winreg.QueryValueEx(registry_key, "pv")
            except OSError:
                continue
            if cls._is_usable_webview2_version(version):
                return version.strip()
        return None

    @classmethod
    def _require_webview2_runtime(cls):
        """确认 WebView2 Runtime 已安装，缺失时给出可操作的错误信息。"""
        version = cls._get_webview2_runtime_version()
        if version is None:
            raise RuntimeError(
                "未检测到 Microsoft Edge WebView2 Runtime，无法启动控制中心。"
                "请安装 Evergreen WebView2 Runtime 后重试：{}".format(
                    WEBVIEW2_DOWNLOAD_URL
                )
            )
        return version

    @staticmethod
    def _require_dotnet_framework_462():
        """确认 WinForms WebView2 后端所需的 .NET Framework 4.6.2 已安装。"""
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                DOTNET_FRAMEWORK_FULL_KEY,
            ) as registry_key:
                release, _ = winreg.QueryValueEx(registry_key, "Release")
        except (OSError, TypeError) as error:
            raise RuntimeError(
                "未检测到 .NET Framework 4.6.2 或更高版本，"
                "无法启动 EdgeChromium 控制中心。"
            ) from error
        if not isinstance(release, int) or release < DOTNET_FRAMEWORK_462_RELEASE:
            raise RuntimeError(
                ".NET Framework 版本过低，请升级到 4.6.2 或更高版本后重试。"
            )
        return release

    def _prepare_webview_icon(self):
        """将统一 PNG 应用图标转换为 Windows WebView 可识别的 ICO。"""
        from PIL import Image

        source_path = self._resource_path("icon", "icon.png")
        target_path = self.data_directory / "icon.ico"
        icon_sizes = (
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        )
        with Image.open(source_path) as source_image:
            source_image.convert("RGBA").save(
                target_path,
                format="ICO",
                sizes=icon_sizes,
            )
        return target_path

    def _initialize_webview(self):
        """在主线程创建常驻隐藏窗口，保证 Windows GUI 消息循环合法。"""
        import webview

        entry = self._resource_path("win", "ui-web", "dist", "index.html")
        if not entry.is_file():
            raise FileNotFoundError("Web 界面构建产物不存在：{}".format(entry))
        bridge = getattr(self, "webview_bridge", None)
        if bridge is None:
            bridge = WebViewBridge(self)
            self.webview_bridge = bridge
        window = webview.create_window(
            "{} — 控制中心".format(APPLICATION_NAME),
            entry.resolve().as_uri(),
            js_api=bridge,
            width=1120,
            height=760,
            min_size=(920, 640),
            background_color="#0b1020",
            confirm_close=False,
            hidden=True,
            minimized=False,
        )

        def hide_instead_of_closing():
            """把用户关闭操作转换为隐藏，保持托盘和主 GUI 循环运行。"""
            if self.stopping.is_set():
                return True
            window.hide()
            return False

        window.events.closing += hide_instead_of_closing
        self.webview_window = window
        self.settings_window = window
        return window

    def _apply_http_admin_settings(self):
        """按照当前 Windows 设置启动、停止或重建 HTTP 管理服务。"""
        enabled = bool(self.settings.get("http_enabled", False))
        current = getattr(self, "http_admin_server", None)
        desired = (
            int(self.settings.get("http_port", 9876)),
            str(self.settings.get("http_auth") or "").strip(),
        )
        if current is not None:
            unchanged = (
                current.port == desired[0]
                and current.auth == desired[1]
            )
            if enabled and unchanged:
                return
            current.stop()
            self.http_admin_server = None
        if not enabled:
            return
        bridge = getattr(self, "webview_bridge", None)
        if bridge is None:
            bridge = WebViewBridge(self)
            self.webview_bridge = bridge
        try:
            server = HttpAdminServer(
                bridge=bridge,
                static_directory=self._resource_path("win", "ui-web", "dist"),
                host="0.0.0.0",
                port=desired[0],
                auth=desired[1],
            )
            server.start()
            self.http_admin_server = server
            if server.port != desired[0]:
                self.settings["http_port"] = server.port
                self.settings_store.save(self.settings)
                icon = getattr(self, "icon", None)
                if icon is not None:
                    icon.notify(
                        "配置端口 {} 无法监听，HTTP 管理页面已自动切换到端口 {}".format(
                            desired[0],
                            server.port,
                        ),
                        APPLICATION_NAME,
                    )
            return True
        except Exception as error:
            LOGGER.exception("应用 HTTP 管理页面设置失败")
            self.http_admin_server = None
            icon = getattr(self, "icon", None)
            if icon is not None:
                icon.notify(
                    "HTTP 管理页面启动失败，请检查端口 {} 是否被占用或被系统保留：{}".format(
                        desired[0],
                        error,
                    ),
                    APPLICATION_NAME,
                )
            return False

    def _schedule_http_admin_settings(self):
        """延迟应用 HTTP 设置，确保当前 WebSocket 保存响应可以先发送完成。"""
        import threading

        timer = threading.Timer(0.25, self._apply_http_admin_settings)
        timer.daemon = True
        timer.start()

    def _stop_http_admin(self):
        """停止 Windows HTTP 管理服务并释放监听端口。"""
        server = getattr(self, "http_admin_server", None)
        if server is not None:
            server.stop()
            self.http_admin_server = None

    def _prepare_webview_runtime(self):
        """在启动后台线程前校验 Edge WebView2 与 .NET 运行环境。"""
        runtime_version = self._require_webview2_runtime()
        self._require_dotnet_framework_462()
        self.webview2_runtime_version = runtime_version
        return runtime_version

    def _start_webview_loop(self):
        """使用独立数据目录启动 Edge WebView2 消息循环。"""
        import webview

        runtime_version = getattr(self, "webview2_runtime_version", None)
        if runtime_version is None:
            runtime_version = self._prepare_webview_runtime()
        storage_path = self.data_directory / "webview2"
        storage_path.mkdir(parents=True, exist_ok=True)
        LOGGER.info("使用 Microsoft Edge WebView2 Runtime %s", runtime_version)
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(storage_path),
            icon=str(self._prepare_webview_icon()),
        )

    def _show_web_page(self, page="settings"):
        """恢复常驻 Web 窗口并导航到指定页面。"""
        window = getattr(self, "webview_window", None)
        if window is None:
            if self.icon is not None:
                self.icon.notify("界面尚未就绪，请稍后重试", APPLICATION_NAME)
            return
        try:
            # 必须先退出最小化状态再显示，否则 WinForms 激活的仍是最小化窗口，
            # 后续恢复只会留下任务栏图标而不会把窗口带到前台。
            window.restore()
            window.show()
            window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('omniwatch:navigate',"
                " {detail: %s}))" % json.dumps(page)
            )
        except Exception as error:
            LOGGER.exception("恢复 Web 界面失败：%s", error)
            if self.icon is not None:
                self.icon.notify("界面恢复失败：{}".format(error), APPLICATION_NAME)

    def _show_settings(self, icon=None, item=None):
        """打开 Web 设置页。"""
        del icon, item
        self._show_web_page("settings")

    def _show_device_probe(self, icon=None, item=None):
        """打开 Web 设备管理页。"""
        del icon, item
        self._show_web_page("device")

    def _show_custom_style(self, icon=None, item=None):
        """打开 Web 屏幕样式页。"""
        del icon, item
        self._show_web_page("styles")

    def _show_custom_data(self, icon=None, item=None):
        """打开 Web 自定义数据页。"""
        del icon, item
        self._show_web_page("data")

    def _show_log(self, icon=None, item=None):
        """打开 Web 日志页。"""
        del icon, item
        self._show_web_page("logs")

    def _show_about(self, icon=None, item=None):
        """打开 Web 关于页。"""
        del icon, item
        self._show_web_page("about")
