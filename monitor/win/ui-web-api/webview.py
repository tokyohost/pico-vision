"""Windows pywebview 窗口的创建、启动和页面导航能力。"""

import json
import logging

from ..constants import APPLICATION_NAME
from .bridge import WebViewBridge


LOGGER = logging.getLogger("pico-monitor.web-ui")


class WebUiMixin:
    """把原有多个 Tk 窗口替换为单一 pywebview Vue 应用。"""

    __slots__ = ()

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
        bridge = WebViewBridge(self)
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

    def _start_webview_loop(self):
        """使用统一应用图标启动 Edge WebView2 消息循环。"""
        import webview

        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=False,
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
            window.evaluate_js(
                "window.dispatchEvent(new CustomEvent('omniwatch:navigate',"
                " {detail: %s}))" % json.dumps(page)
            )
            window.show()
            window.restore()
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

