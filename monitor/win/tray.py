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
import threading
import winreg
from datetime import datetime
from pathlib import Path

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from windows_update import WindowsReleaseUpdater

from .constants import APPLICATION_NAME, MONITOR_DIRECTORY, WINDOWS_APP_USER_MODEL_ID
from .autostart import AutostartMixin
from .log_service import LogServiceMixin
from .worker_controller import WorkerControllerMixin
from .ui import (
    AboutWindowMixin,
    CustomDataWindowMixin,
    CustomStyleWindowMixin,
    DeviceWindowMixin,
    WifiWindowMixin,
    WebSocketClientsWindowMixin,
    LogWindowMixin,
    SettingsWindowMixin,
    TkSupportMixin,
)

from .settings import (
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
MONITOR_DIRECTORY = Path(__file__).resolve().parent.parent
LOG_EXPORT_SIZE = 1024 * 1024
LOGGER = logging.getLogger("pico-monitor.windows-update")


class WindowsTrayApplication(
    WorkerControllerMixin,
    LogServiceMixin,
    AutostartMixin,
    SettingsWindowMixin,
    DeviceWindowMixin,
    WifiWindowMixin,
    WebSocketClientsWindowMixin,
    LogWindowMixin,
    AboutWindowMixin,
    CustomDataWindowMixin,
    CustomStyleWindowMixin,
    TkSupportMixin,
):
    """管理 Windows 托盘图标、配置界面和无窗口监控工作进程。"""

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

    def __init__(self, worker_arguments):
        """初始化托盘状态、窗口互斥量、配置存储和后台进程参数。"""
        self.worker_arguments = list(worker_arguments)
        self.worker_process = None
        self.log_file_lock = threading.Lock()
        self.log_window_lock = threading.Lock()
        self.log_window_open = False
        self.stopping = threading.Event()
        self.icon = None
        self.mutex = None
        self.settings_window = None
        self.settings_window_lock = threading.Lock()
        self.settings_window_open = False
        self.settings_window_restore_requested = threading.Event()
        self.about_window_lock = threading.Lock()
        self.about_window_open = False
        self.device_probe_window_lock = threading.Lock()
        self.device_probe_window_open = False
        self.device_management_messages = queue.Queue()
        self.sdk_flash_messages = queue.Queue()
        self.device_connection_messages = queue.Queue()
        self.wifi_messages = queue.Queue()
        self.websocket_client_messages = queue.Queue()
        self.device_connection_lock = threading.Lock()
        self.current_device_connection = {"connected": None}
        self.custom_style_messages = queue.Queue()
        self.custom_style_upload_messages = queue.Queue()
        self.custom_style_upload_logs = queue.Queue()
        self.custom_style_upload_active = threading.Event()
        self.custom_style_delete_messages = queue.Queue()
        self.update_lock = threading.Lock()
        self.crash_dialog_lock = threading.Lock()
        data_directory = Path(os.getenv("LOCALAPPDATA", Path.home())) / "PicoMonitor"
        data_directory.mkdir(parents=True, exist_ok=True)
        self.data_directory = data_directory
        self.screenshot_directory = data_directory / "screenshot"
        self.log_path = data_directory / "pico-monitor.log"
        self._configure_error_logging()
        self.settings_store = TraySettingsStore(data_directory / "settings.json")
        settings_existed = self.settings_store.path.exists()
        self.settings = self.settings_store.load()
        if not settings_existed:
            self.settings = settings_from_arguments(self.worker_arguments, self.settings)
            self.settings_store.save(self.settings)

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
























    def _is_dev_mode(self, item=None):
        """返回托盘配置中的开发模式开关状态。"""
        del item
        return bool(self.settings.get("dev"))

    def _toggle_dev_mode(self, icon, item):
        """切换开发模式并通知后台监控进程即时生效。"""
        del item
        self.settings["dev"] = not self._is_dev_mode()
        self.settings_store.save(self.settings)
        applied = self._apply_dev_settings()
        icon.update_menu()
        state = "开启" if self.settings["dev"] else "关闭"
        if applied:
            icon.notify("开发模式已{}".format(state), APPLICATION_NAME)
        else:
            icon.notify(
                "开发模式已{}，后台监控下次启动时生效".format(state),
                APPLICATION_NAME,
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
        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION)
        self._perform_update(icon, updater.default_update_url())

    def _ask_update_url(self):
        """显示更新地址输入框，返回确认后的 HTTP 地址。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox

        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION)
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
        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION)
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
            pico_asset = updater.select_pico_asset(assets, latest_version)
            monitor_asset = updater.select_monitor_asset(assets, latest_version)
            icon.notify("发现版本 {}，正在下载更新".format(latest_version), APPLICATION_NAME)
            pico_path = updater.download(pico_asset, ".zip")
            monitor_path = updater.download(monitor_asset, ".exe")
            self._stop_worker()
            self._upgrade_pico_from_package(pico_path)
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

    def _upgrade_pico_from_package(self, package_path):
        """启动一次性隐藏进程，把已下载升级包发送给 Pico。"""
        command = self._worker_command() + [
            "--upgrade-pico",
            "--upgrade-url", Path(package_path).resolve().as_uri(),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=0x08000000,
            timeout=300,
        )
        if result.returncode != 0:
            message = (result.stdout or result.stderr or "OmniWatch 升级进程异常退出").strip()
            raise RuntimeError(message[-500:])

    @staticmethod
    def _schedule_monitor_installer(download_path):
        """由独立 PowerShell 进程等待托盘退出后运行安装包。"""
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

    def _select_style(self, style):
        """创建切换指定屏幕样式的托盘回调。"""
        def select(icon, item):
            """保存选中样式并通知后台进程即时应用。"""
            del item
            self.settings["lcd_style"] = style
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
            icon.notify("已切换为{}".format(style_names(self.settings, idle=False)[style]), APPLICATION_NAME)
        return select

    def _style_checked(self, style):
        """创建判断指定屏幕样式是否选中的回调。"""
        return lambda item: self.settings["lcd_style"] == style














    def _exit(self, icon, item):
        """退出 Windows Monitor，不向 Pico 发送重启指令。"""
        del item
        self.stopping.set()
        self._stop_worker()
        icon.stop()

    @staticmethod
    def _create_image():
        """加载托盘图标并转换为带透明通道的图像。"""
        from PIL import Image

        base_directory = Path(getattr(sys, "_MEIPASS", MONITOR_DIRECTORY))
        with Image.open(base_directory / "icon" / "icon.png") as image:
            return image.convert("RGBA")

    @staticmethod
    def _resource_path(*parts):
        """返回开发目录或单文件程序解包目录中的资源绝对路径。"""
        base_directory = Path(getattr(sys, "_MEIPASS", MONITOR_DIRECTORY))
        return base_directory.joinpath(*parts)




    def _build_menu(self):
        """构建托盘主菜单，样式子菜单在每次展开时动态读取最新清单。"""
        import pystray

        style_menu = pystray.Menu(self._style_menu_items)
        return pystray.Menu(
            pystray.MenuItem("配置...", self._show_settings, default=True),
            pystray.MenuItem("界面样式", style_menu),
            pystray.MenuItem("自定义屏幕", self._show_custom_style),
            pystray.MenuItem("自定义数据", self._show_custom_data),
            pystray.MenuItem("屏幕旋转", pystray.Menu(
                pystray.MenuItem("0°", self._set_rotation(0), checked=lambda item: self.settings["screen_rotation"] == 0, radio=True),
                pystray.MenuItem("180°", self._set_rotation(180), checked=lambda item: self.settings["screen_rotation"] == 180, radio=True),
            )),
            pystray.MenuItem("屏幕截图", self._take_screenshot),
            pystray.MenuItem("打开日志", self._show_log),
            pystray.MenuItem("设备管理", self._show_device_probe),
            pystray.MenuItem("日志导出", self._export_log),
            pystray.MenuItem("检查更新", self._check_for_updates),
            pystray.MenuItem("关于应用", self._show_about),
            pystray.MenuItem("Dev 模式", self._toggle_dev_mode, checked=self._is_dev_mode),
            pystray.MenuItem("开机自动启动", self._toggle_autostart, checked=self._is_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit),
        )


    def request_custom_style_catalog(self):
        """向工作进程发送自定义样式清单查询请求。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write("CUSTOM_STYLE_LIST\n")
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def request_custom_style_upload(self, path, existing_style_names, overwrite=False):
        """校验本地样式文件、检查重名并交给 Monitor 工作进程上传。"""
        from style_validator import StyleFileValidator

        validated = StyleFileValidator().validate(path)
        existing_filenames = {
            "style_{}.py".format(name) for name in existing_style_names
        }
        if validated.filename in existing_filenames and not overwrite:
            raise FileExistsError(
                "OmniWatch 中已存在样式名 {} 和文件 {}".format(
                    validated.name, validated.filename,
                )
            )
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("OmniWatch 未运行，无法上传样式")
        payload = {
            "filename": validated.filename,
            "style_name": validated.name,
            "content": base64.b64encode(validated.source).decode("ascii"),
            "overwrite": bool(overwrite),
        }
        upload_active = getattr(self, "custom_style_upload_active", None)
        if upload_active is not None:
            upload_active.set()
        try:
            process.stdin.write(
                "CUSTOM_STYLE_UPLOAD:{}\n".format(
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                )
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            if upload_active is not None:
                upload_active.clear()
            raise RuntimeError("自定义样式上传请求发送失败") from error
        return validated

    def request_custom_style_delete(self, style_name, filename):
        """向工作进程发送自定义样式删除请求。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("OmniWatch 未运行，无法删除样式")
        payload = {"style_name": style_name, "filename": filename}
        try:
            process.stdin.write(
                "CUSTOM_STYLE_DELETE:{}\n".format(
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                )
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise RuntimeError("自定义样式删除请求发送失败") from error

    def _reload_style_catalog(self):
        """从配置文件同步 Pico 样式清单及当前选择。"""
        latest_settings = self.settings_store.load()
        self.settings["styles"] = normalize_style_catalog(latest_settings["styles"])
        self.settings["lcd_style"] = latest_settings["lcd_style"]
        self.settings["idle_style"] = latest_settings["idle_style"]

    def _style_menu_items(self):
        """生成最新的样式菜单项，避免托盘长期持有启动时的静态清单。"""
        import pystray

        self._reload_style_catalog()
        return tuple(
            pystray.MenuItem(style_label(name, self.settings), self._select_style(name), checked=self._style_checked(name), radio=True)
            for name in style_names(self.settings, idle=False)
        )

    def _set_rotation(self, rotation):
        """创建设置指定屏幕旋转角度的托盘回调。"""
        def select(icon, item):
            """保存屏幕旋转角度并通知后台进程即时应用。"""
            del item
            self.settings["screen_rotation"] = rotation
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
        return select

    def run(self):
        """配置 Windows 应用标识并启动后台工作进程与托盘消息循环。"""
        import pystray

        original_thread_hook = self._install_thread_crash_handler()
        try:
            self._configure_windows_taskbar()
            if not self._acquire_single_instance():
                return 0
            self._start_worker()
            self.icon = pystray.Icon("pico-monitor", self._create_image(), APPLICATION_NAME, self._build_menu())
            self.icon.run()
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
            self._stop_worker()
            threading.excepthook = original_thread_hook
