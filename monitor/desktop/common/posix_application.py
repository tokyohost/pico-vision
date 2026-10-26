"""Linux/macOS 桌面的公共生命周期，不改变 Linux 默认无桌面入口。"""

from i18n import t

import logging
import sys
import threading

from .application import DesktopApplication
from .constants import APPLICATION_NAME
from .single_instance import SingleInstanceLock


LOGGER = logging.getLogger("pico-monitor.desktop")


class DesktopIcon:
    """为菜单栏统一提供通知入口，避免不支持 notify 的后端抛出异常。"""

    def __init__(self, icon, notifier):
        """保存原生托盘对象和平台通知函数。"""
        self._icon = icon
        self._notifier = notifier

    def __getattr__(self, name):
        """将菜单更新及生命周期操作交给原生托盘对象。"""
        return getattr(self._icon, name)

    def notify(self, message, title=APPLICATION_NAME):
        """通知失败不影响采集与界面，错误仍写入日志。"""
        try:
            self._notifier(str(message), str(title))
        except Exception:
            LOGGER.exception("发送桌面通知失败")


class PosixDesktopApplication(DesktopApplication):
    """维护托盘、共享 Vue 窗口和后台采集进程的退出顺序。"""

    @classmethod
    def start(cls, worker_arguments):
        """在启动保护边界构造应用，并输出可诊断的启动失败日志。"""
        try:
            return cls(worker_arguments).run()
        except Exception:
            LOGGER.exception("桌面应用启动失败")
            return 1

    def _prepare_webview_runtime(self):
        """POSIX 使用系统 WebKit，不检查 Windows WebView2 或注册表。"""
        import webview
        import pystray
        del webview, pystray

    def _native_icon_options(self):
        """默认不附加原生托盘参数，由 macOS 子类提供共享 Cocoa 应用。"""
        return {}

    def _notify(self, message, title):
        """Linux 后端支持时发送通知，否则仅记录诊断信息。"""
        native = self.icon._icon
        if native.HAS_NOTIFICATION:
            native.notify(message, title)
        else:
            LOGGER.info("%s：%s", title, message)

    def _start_platform_services(self):
        """为平台休眠监听和通知授权保留启动扩展点。"""
        return None

    def _stop_platform_services(self):
        """为平台监听对象释放保留退出扩展点。"""
        return None

    def _check_for_updates(self, icon=None, item=None):
        """统一在 Vue 更新页检查升级，避免从后台线程创建原生对话框。"""
        del icon, item
        self._show_web_page("update")

    def _is_autostart(self, item=None):
        """读取平台启动项状态，而不是维护容易过时的内存标记。"""
        del item
        return self.autostart.is_enabled()

    def _toggle_autostart(self, icon, item=None):
        """切换启动项，失败只通知用户，不中断采集。"""
        del item
        try:
            enabled = not self._is_autostart()
            self.autostart.set_enabled(enabled)
            icon.update_menu()
            self.icon.notify(t('message.start_at_login_2').format(t('message.enabled') if enabled else t('ui.close')))
        except Exception as error:
            LOGGER.exception("修改启动项失败")
            self.icon.notify(t('message.failed_to_change_startup_setting').format(error))

    def run(self):
        """在主线程启动共享 GUI 循环，任意退出路径都回收 worker 和锁。"""
        import pystray

        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError(t('message.desktop_gui_must_start_on_the_main_thread'))
        instance = SingleInstanceLock(self.data_directory / "desktop.lock")
        if not instance.acquire():
            return 0
        try:
            self._prepare_webview_runtime()
            native = pystray.Icon("omniwatch", self._create_image(), APPLICATION_NAME,
                                  self._build_menu(), **self._native_icon_options())
            self.icon = DesktopIcon(native, self._notify)
            self._initialize_webview()
            self._start_worker()
            self._start_platform_services()
            self._apply_http_admin_settings()
            native.run_detached()
            self._start_webview_loop()
            return 0
        finally:
            self.stopping.set()
            try:
                self._stop_platform_services()
            finally:
                try:
                    self._stop_http_admin()
                finally:
                    try:
                        if self.icon is not None:
                            self.icon.stop()
                    finally:
                        try:
                            self._stop_worker()
                        finally:
                            instance.close()
