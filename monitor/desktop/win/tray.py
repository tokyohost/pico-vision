#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.

"""Windows 托盘、配置窗口、开机自启和后台进程管理。"""

import ctypes
import base64
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import winreg
from datetime import datetime
from pathlib import Path

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from pico_upgrade import PicoFirmwareArchive
from windows_update import WindowsReleaseUpdater

from desktop.common.constants import APPLICATION_NAME, MONITOR_DIRECTORY, WINDOWS_APP_USER_MODEL_ID
from .autostart import AutostartMixin
from desktop.common.log_service import LogServiceMixin
from desktop.common.ui_api.webview import WebUiMixin
from desktop.common.worker_controller import WorkerControllerMixin
from .power_events import WindowsPowerNotifications
from .ui import TkSupportMixin
from desktop.common.application import DesktopApplication
from .webview import WindowsWebUiMixin

from desktop.common.settings import (
    DEFAULT_SETTINGS,
    TraySettingsStore,
    apply_worker_arguments,
    normalize_style_catalog,
    settings_from_arguments,
    style_label,
    style_names,
)

WINDOWS_APP_USER_MODEL_ID = "OmniWatch.USBMonitor.Tray"
AUTOSTART_NAME = "PicoHardwareMonitor"
MONITOR_DIRECTORY = Path(__file__).resolve().parents[2]
LOG_EXPORT_SIZE = 1024 * 1024
LOGGER = logging.getLogger("pico-monitor.windows-update")


class WindowsTrayApplication(AutostartMixin, TkSupportMixin, WindowsWebUiMixin, DesktopApplication):
    """管理 Windows 托盘图标、配置界面和无窗口监控工作进程。"""

    application_asset_suffix = ".exe"

    @staticmethod
    def _copy_text(text):
        """为原生页面提供 Windows 剪贴板兜底。"""
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def _create_release_updater(repository, current_version, include_preview=False):
        """保持 Windows 发布资源与原有升级器一致。"""
        return WindowsReleaseUpdater(repository, current_version, include_preview=include_preview)

    @classmethod
    def start(cls, worker_arguments):
        """在启动保护边界内构造并运行托盘，捕获初始化阶段异常。"""
        try:
            application = cls(worker_arguments)
        except Exception:
            exception_type, exception, traceback_object = sys.exc_info()
            application = cls.__new__(cls)
            application.data_directory = Path(
                os.getenv("LOCALAPPDATA", Path.home())
            ) / "PicoMonitor"
            application.data_directory.mkdir(parents=True, exist_ok=True)
            application._configure_error_logging()
            application.settings_window = None
            application.crash_dialog_lock = threading.Lock()
            application._report_unhandled_crash(
                exception_type,
                exception,
                traceback_object,
                "托盘启动线程",
            )
            return 1
        return application.run()


    def _acquire_single_instance(self):
        """获取进程互斥锁，避免重复启动多个托盘实例。"""
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PicoHardwareMonitor")
        return ctypes.windll.kernel32.GetLastError() != 183

    @staticmethod
    def _configure_windows_taskbar():
        """设置独立的 Windows 应用标识，使任务栏采用程序窗口和 EXE 图标。"""
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )


























    def _check_for_updates(self, icon, item=None):
        """启动独立线程显示地址弹框并执行联合更新。"""
        del item
        if not self.update_lock.acquire(blocking=False):
            icon.notify("更新任务正在执行，请稍候", APPLICATION_NAME)
            return
        threading.Thread(
            target=self._prompt_and_perform_update,
            args=(icon,),
            name="在线更新",
            daemon=True,
        ).start()

    def _prompt_and_perform_update(self, icon):
        """使用固定发布仓库地址执行在线更新。"""
        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION, include_preview=bool(self.settings.get("developer_plan", False)))
        self._perform_update(icon, updater.default_update_url())

    def _ask_update_url(self):
        """显示更新地址输入框，返回确认后的 HTTP 地址。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox

        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION, include_preview=bool(self.settings.get("developer_plan", False)))
        initial_url = self.settings.get("update_url") or updater.default_update_url()
        root = tk.Tk()
        self._set_tk_window_icon(root)
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            update_url = self._show_update_url_input(root, initial_url)
            if update_url is None:
                return None
            update_url = update_url.strip()
            if not update_url:
                # 空值表示跟随正式构建内置的默认更新地址，不持久化固定地址。
                return initial_url
            if not update_url.lower().startswith(("https://", "http://")):
                messagebox.showerror("检查更新", "请输入有效的 HTTP 或 HTTPS 地址", parent=root)
                return None
            return update_url
        finally:
            root.destroy()

    @staticmethod
    def _show_update_url_input(root, initial_url):
        """显示加宽约三分之二的更新地址输入对话框。"""
        from tkinter import simpledialog

        class WideUpdateUrlDialog(simpledialog._QueryString):
            """把标准字符串输入框扩展到适合显示完整更新地址的宽度。"""

            def body(self, master):
                """创建标准输入控件并将字符宽度从 50 调整为 84。"""
                entry = super().body(master)
                self.entry.configure(width=84)
                self.after_idle(
                    lambda: WindowsTrayApplication._center_tk_window(self)
                )
                return entry

        dialog = WideUpdateUrlDialog(
            "检查更新",
            "更新地址：",
            initialvalue=initial_url,
            parent=root,
        )
        return dialog.result

    def _perform_update(self, icon, update_url):
        """检查最新 Release，经用户确认后升级 Pico 并安装 Monitor。"""
        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION, include_preview=bool(self.settings.get("developer_plan", False)))
        monitor_path = None
        pico_path = None
        try:
            icon.notify("正在检查最新版本", APPLICATION_NAME)
            latest_version, assets, release_notes = updater.latest_release(
                update_url,
                include_notes=True,
            )
            if not updater.update_available(latest_version):
                icon.notify("当前已是最新版本：{}".format(MONITOR_VERSION), APPLICATION_NAME)
                return
            if not self._confirm_application_update(latest_version, release_notes):
                icon.notify("已取消 OmniWatch 更新", APPLICATION_NAME)
                return
            connection = self._get_device_connection()
            port = self._mpremote_repl_port(connection)
            pico_asset = updater.select_pico_asset(
                assets,
                latest_version,
                connection.get("board_model"),
                connection.get("lcd_device_type"),
            )
            monitor_asset = updater.select_monitor_asset(assets, latest_version)
            icon.notify("发现版本 {}，正在下载更新".format(latest_version), APPLICATION_NAME)
            pico_path = updater.download(pico_asset, ".zip")
            monitor_path = updater.download(monitor_asset, ".exe")
            self._stop_worker()
            self._install_pico_firmware_archive(pico_path, port)
            updater.remove_file(pico_path)
            pico_path = None
            self._schedule_monitor_installer(monitor_path)
            monitor_path = None
            self.stopping.set()
            icon.notify("OmniWatch 更新完成，应用即将重启", APPLICATION_NAME)
            icon.stop()
        except Exception as error:
            LOGGER.exception("检查或安装更新失败：%s", error)
            icon.notify("检查或安装更新失败，请查看日志", APPLICATION_NAME)
            if not self.stopping.is_set() and (
                self.worker_process is None or self.worker_process.poll() is not None
            ):
                self._start_worker()
        finally:
            if pico_path is not None:
                updater.remove_file(pico_path)
            if monitor_path is not None:
                updater.remove_file(monitor_path)
            self.update_lock.release()

    def _confirm_application_update(self, latest_version, release_notes):
        """显示应用更新确认弹窗，并展示目标版本及 Release 更新说明。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        self._set_tk_window_icon(root)
        root.withdraw()
        try:
            root.attributes("-topmost", True)
            return messagebox.askyesno(
                "检查更新",
                "发现新版本 {}，当前版本为 {}。\n\n"
                "更新说明：\n{}\n\n"
                "是否立即更新？".format(
                    latest_version,
                    MONITOR_VERSION,
                    release_notes or "暂无更新说明",
                ),
                parent=root,
            )
        finally:
            root.destroy()


    @staticmethod
    def _schedule_monitor_installer(download_path, version=None):
        """由独立 PowerShell 进程等待托盘退出后运行安装包。"""
        del version
        environment = os.environ.copy()
        environment.update({
            "PICO_UPDATE_PID": str(os.getpid()),
            "PICO_UPDATE_SOURCE": str(Path(download_path).resolve()),
            "PICO_UPDATE_TARGET": str(Path(sys.executable).resolve()),
        })
        command = (
            "Wait-Process -Id $env:PICO_UPDATE_PID -ErrorAction SilentlyContinue;"
            "$process = Start-Process -FilePath $env:PICO_UPDATE_SOURCE "
            "-ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru;"
            "if ($process.ExitCode -eq 0) { Start-Process -FilePath $env:PICO_UPDATE_TARGET; };"
            "Remove-Item -LiteralPath $env:PICO_UPDATE_SOURCE -Force -ErrorAction SilentlyContinue"
        )
        subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            env=environment,
            creationflags=0x08000000,
        )

















    def _handle_windows_resume(self):
        """通知后台丢弃失效连接并重新发现设备。"""
        LOGGER.info("检测到 Windows 从休眠恢复，通知 Monitor 重新扫描设备")
        if not self._write_worker_command("RESUME_PROBE\n"):
            LOGGER.warning("Windows 恢复后无法通知 Monitor worker 重新扫描设备")














    def run(self):
        """配置 Windows 应用标识并启动后台工作进程与托盘消息循环。"""
        import pystray

        original_thread_hook = self._install_thread_crash_handler()
        power_notifications = WindowsPowerNotifications(
            self._handle_windows_resume
        )
        try:
            self._configure_windows_taskbar()
            if not self._acquire_single_instance():
                return 0
            self._prepare_webview_runtime()
            self._start_worker()
            power_notifications.start()
            self.icon = pystray.Icon("pico-monitor", self._create_image(), APPLICATION_NAME, self._build_menu())
            self._initialize_webview()
            self._apply_http_admin_settings()
            self.icon.run_detached()
            self._start_webview_loop()
            return 0
        except Exception:
            exception_type, exception, traceback_object = sys.exc_info()
            self._report_unhandled_crash(
                exception_type,
                exception,
                traceback_object,
            )
            return 1
        finally:
            self.stopping.set()
            power_notifications.stop()
            self._stop_http_admin()
            if self.icon is not None:
                try:
                    self.icon.stop()
                except Exception:
                    LOGGER.exception("停止 Windows 托盘图标失败")
            self._stop_worker()
            threading.excepthook = original_thread_hook
