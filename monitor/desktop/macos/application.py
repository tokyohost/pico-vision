"""macOS 菜单栏与 WKWebView 桌面适配，复用公共业务层。"""

import logging
from importlib import import_module
import os
import sys
import threading
from pathlib import Path

from desktop.common.constants import MONITOR_DIRECTORY
from desktop.common.posix_application import PosixDesktopApplication
from .autostart import MacOsAutostart
from .native import MacOsNotifications, MacOsWakeObserver, copy_text


LOGGER = logging.getLogger("pico-monitor.macos")


class MacOsDesktopApplication(PosixDesktopApplication):
    """保持关闭窗口只隐藏、菜单退出才停止采集的桌面行为。"""

    application_asset_suffix = ".zip"

    def __init__(self, worker_arguments):
        """初始化公共状态与平台服务，不在构造阶段启动 Cocoa 循环。"""
        super().__init__(worker_arguments)
        command = [str(Path(sys.executable).resolve())]
        if not getattr(sys, "frozen", False):
            command.append(str(MONITOR_DIRECTORY / "pico_monitor.py"))
        self.autostart = MacOsAutostart([*command, "--desktop"])
        self.notifications = MacOsNotifications()
        self.wake_observer = MacOsWakeObserver(self._handle_resume)

    def _prepare_webview_runtime(self):
        """预加载固定 Cocoa 后端并恢复菜单栏策略，避免 pywebview 默认显示 Dock。"""
        super()._prepare_webview_runtime()
        # pywebview 5.4 的 Cocoa 类初始化会设置 Regular 策略；预加载后覆盖为
        # Accessory，随后 start 复用缓存模块，不会再次把菜单栏应用放入 Dock。
        import_module("webview.platforms.cocoa")
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def _native_icon_options(self):
        """托盘和 WKWebView 共用 NSApplication，避免两个原生事件循环。"""
        from AppKit import NSApplication
        return {"darwin_nsapplication": NSApplication.sharedApplication()}

    def _start_webview_loop(self):
        """在主线程使用系统 Cocoa/WKWebView，不使用 Edge 或 Qt。"""
        import webview
        storage = self.data_directory / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        # 用户环境的 PYWEBVIEW_GUI=qt 不能把菜单栏应用切换到第二个 GUI 循环。
        previous_backend = os.environ.pop("PYWEBVIEW_GUI", None)
        try:
            webview.start(debug=False, private_mode=False, storage_path=str(storage))
        finally:
            if previous_backend is not None:
                os.environ["PYWEBVIEW_GUI"] = previous_backend

    def _show_web_page(self, page="settings"):
        """原生窗口操作留在主线程，JavaScript 等待不得阻塞 Cocoa 消息循环。"""
        if self.stopping.is_set():
            return
        window = getattr(self, "webview_window", None)
        if window is None:
            return super()._show_web_page(page)
        from AppKit import NSApplication
        from PyObjCTools.AppHelper import callAfter

        def navigate():
            """后台等待 WKWebView 结果，回调仍由 Cocoa 主线程正常执行。"""
            if self.stopping.is_set():
                return
            try:
                self._navigate_web_page(window, page)
            except Exception:
                LOGGER.exception("macOS Vue 页面导航失败：%s", page)

        def show():
            """在主队列恢复、显示和激活窗口，再异步发送公共 Vue 导航事件。"""
            if self.stopping.is_set():
                return
            try:
                window.restore()
                window.show()
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                # pywebview 5.4 的 evaluate_js 会投递主队列任务并等待信号量。
                # 从菜单的主线程直接调用会死锁；原生 restore 则必须留在主线程。
                threading.Thread(target=navigate, name="macOS Vue 页面导航", daemon=True).start()
            except Exception:
                LOGGER.exception("恢复 macOS Web 界面失败")

        callAfter(show)

    def _start_platform_services(self):
        """注册系统唤醒监听，并在 GUI 循环就绪后请求通知授权。"""
        self.wake_observer.start()
        from PyObjCTools.AppHelper import callAfter

        def request_notifications():
            """通知授权失败只写日志，不影响托盘启动或后台采集。"""
            try:
                self.notifications.start()
            except Exception:
                LOGGER.exception("初始化 macOS 通知失败")

        callAfter(request_notifications)

    def _stop_platform_services(self):
        """退出前取消系统唤醒监听。"""
        self.wake_observer.stop()

    def _handle_resume(self):
        """复用既有 RESUME_PROBE 命令，使 USB 与 Wi-Fi 恢复后重连。"""
        if not self.stopping.is_set():
            self._write_worker_command("RESUME_PROBE\n")

    def _notify(self, message, title):
        """将菜单通知转交原生 UserNotifications 服务。"""
        return self.notifications.send(message, title)

    @staticmethod
    def _copy_text(text):
        """提供 WKWebView 剪贴板失败时的原生纯文本兜底。"""
        copy_text(text)

    @staticmethod
    def _create_release_updater(repository, current_version, include_preview=False):
        """创建按当前进程架构选择签名应用包的更新器。"""
        from .update import MacOsReleaseUpdater
        return MacOsReleaseUpdater(repository, current_version, include_preview=include_preview)

    def _schedule_monitor_installer(self, download_path, version=None):
        """验证签名和架构后启动独立更新助手，等待主进程退出再替换。"""
        from .update import prepare_update
        prepare_update(download_path, expected_version=version)
