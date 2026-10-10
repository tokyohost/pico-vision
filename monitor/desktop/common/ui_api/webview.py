"""共享 pywebview 窗口、HTTP 管理服务与页面导航。"""

import json
import logging
import sys

from desktop.common.constants import APPLICATION_NAME
from .bridge import WebViewBridge
from desktop.common.http_server import HttpAdminServer


LOGGER = logging.getLogger("pico-monitor.web-ui")


class WebUiMixin:
    """把原有多个 Tk 窗口替换为单一 pywebview Vue 应用。"""

    __slots__ = ()






    def _initialize_webview(self):
        """在主线程创建常驻隐藏窗口，保证原生 GUI 消息循环合法。"""
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

        def configure_session_closing():
            """在 Windows 原生窗口首次显示前接入会话结束处理，覆盖隐藏启动场景。"""
            if sys.platform == "win32":
                self._configure_windows_session_closing(window)

        window.events.closing += hide_instead_of_closing
        window.events.before_show += configure_session_closing
        self.webview_window = window
        self.settings_window = window
        return window

    def _apply_http_admin_settings(self):
        """按照当前桌面设置启动、停止或重建 HTTP 管理服务。"""
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
        """停止桌面 HTTP 管理服务并释放监听端口。"""
        server = getattr(self, "http_admin_server", None)
        if server is not None:
            server.stop()
            self.http_admin_server = None



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
