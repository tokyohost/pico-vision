"""Windows pywebview 窗口的创建、启动和页面导航能力。"""

import json
import logging

from desktop.common.constants import APPLICATION_NAME
from desktop.common.ui_api.bridge import WebViewBridge
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


class WindowsWebUiMixin:
    """保留 Windows WebView2 环境检测与启动参数。"""

    @staticmethod
    def _is_usable_webview2_version(version):
        """判断注册表版本值是否表示可用的 WebView2 Runtime。"""
        return isinstance(version, str) and version.strip() not in ("", "0.0.0.0")

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

    def _configure_windows_session_closing(self, window):
        """允许 Windows 关机、重启和注销关闭窗口，保留普通关闭时的托盘行为。"""
        from System.Windows.Forms import CloseReason

        native = window.native
        original_closing = native.on_closing

        def handle_native_closing(sender, event):
            """根据原生关闭原因放行系统会话结束，其余操作交由 pywebview 处理。"""
            if event.CloseReason == CloseReason.WindowsShutDown:
                # pywebview 的 closing 事件不传递关闭原因，必须在 WinForms 层
                # 绕过“隐藏并取消关闭”的回调，否则会拒绝 WM_QUERYENDSESSION。
                # 此时仅允许退出；其他应用可能取消关机，不能提前停止监控。
                event.Cancel = False
                return
            original_closing(sender, event)

        native.FormClosing -= original_closing
        native.FormClosing += handle_native_closing

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
