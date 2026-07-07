#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.

"""Windows 托盘、配置窗口、开机自启和后台进程管理。"""

import ctypes
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
from qbittorrent_monitor import QbittorrentApiClient
from windows_update import WindowsReleaseUpdater

from .settings import (
    DEFAULT_SETTINGS,
    TraySettingsStore,
    apply_worker_arguments,
    settings_from_arguments,
    style_label,
    style_names,
)

APPLICATION_NAME = "OmniWatch USB监控屏"
WINDOWS_APP_USER_MODEL_ID = "OmniWatch.USBMonitor.Tray"
AUTOSTART_NAME = "PicoHardwareMonitor"
MONITOR_DIRECTORY = Path(__file__).resolve().parent.parent
LOG_EXPORT_SIZE = 1024 * 1024
LOGGER = logging.getLogger("pico-monitor.windows-update")


class WindowsTrayApplication:
    """管理 Windows 托盘图标、配置界面和无窗口监控工作进程。"""

    def __init__(self, worker_arguments):
        """初始化托盘状态、窗口互斥量、配置存储和后台进程参数。"""
        self.worker_arguments = list(worker_arguments)
        self.worker_process = None
        self.console_process = None
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
        self.device_connection_messages = queue.Queue()
        self.update_lock = threading.Lock()
        data_directory = Path(os.getenv("LOCALAPPDATA", Path.home())) / "PicoMonitor"
        data_directory.mkdir(parents=True, exist_ok=True)
        self.data_directory = data_directory
        self.log_path = data_directory / "pico-monitor.log"
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

    def _worker_command(self):
        """构造应用当前托盘配置后的后台监控命令。"""
        arguments = apply_worker_arguments(self.worker_arguments, self.settings)
        if getattr(sys, "frozen", False):
            return [sys.executable, *arguments]
        return [sys.executable, str(MONITOR_DIRECTORY / "pico_monitor.py"), *arguments]

    def _device_probe_command(self):
        """构造仅执行一次 Pico 设备探测的子进程命令。"""
        return [argument for argument in self._worker_command() if argument != "--worker"] + ["--pico-info"]

    def _start_worker(self):
        environment = os.environ.copy()
        environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        environment["PICO_MONITOR_SETTINGS_PATH"] = str(self.settings_store.path)
        self.worker_process = subprocess.Popen(
            self._worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            creationflags=0x08000000, env=environment,
        )
        threading.Thread(target=self._collect_output, name="日志收集", daemon=True).start()

    def _stop_worker(self):
        process = self.worker_process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()

    def _restart_worker(self):
        self._stop_worker()
        if not self.stopping.is_set():
            self._start_worker()

    def _apply_display_settings(self):
        """向运行中的 Monitor 下发显示配置，避免重启后台进程。"""
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        payload = {
            "lcd_style": self.settings["lcd_style"],
            "screen_rotation": self.settings["screen_rotation"],
            "lcd_brightness": self.settings["lcd_brightness"],
            "network_unit": self.settings["network_unit"],
        }
        try:
            process.stdin.write(
                "DISPLAY_CONFIG:{}\n".format(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
            )
            process.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def _collect_output(self):
        """收集工作进程日志，并在 Pico 样式清单变化后刷新托盘菜单。"""
        process = self.worker_process
        with self.log_path.open("a", encoding="utf-8", newline="") as log_file:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                if "STYLE_CATALOG_UPDATED" in line:
                    self._reload_style_catalog()
                    if self.icon is not None:
                        self.icon.update_menu()
                if line.startswith("DEVICE_REBOOT_RESULT:"):
                    try:
                        result = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        result = {"status": "error", "message": "设备返回了无效响应"}
                    self.device_management_messages.put(result)
                if "[串口关闭]" in line or "监控通信异常：" in line:
                    self.device_connection_messages.put({"connected": False})
                connection = re.search(
                    r"\[串口连接\].*握手成功：开发板=(.*)，屏幕方案=(.*)，固件版本=(.*)，分辨率=(.*)$",
                    line.strip(),
                )
                if connection:
                    self.device_connection_messages.put({
                        "connected": True,
                        "board_model": connection.group(1),
                        "screen_color_profile": connection.group(2),
                        "firmware_version": connection.group(3),
                        "screen_resolution": connection.group(4),
                    })
        return_code = process.wait()
        if not self.stopping.is_set() and process is self.worker_process and self.icon is not None:
            self.icon.notify("后台监控已退出，返回码：{}".format(return_code), APPLICATION_NAME)

    def _show_log(self, icon=None, item=None):
        """打开独立 PowerShell 窗口并持续显示 Monitor 日志。"""
        del icon, item
        if self.console_process is not None and self.console_process.poll() is None:
            return
        environment = os.environ.copy()
        environment["PICO_MONITOR_LOG"] = str(self.log_path)
        command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$Host.UI.RawUI.WindowTitle='Pico 系统监控日志';Get-Content -LiteralPath $env:PICO_MONITOR_LOG -Encoding UTF8 -Tail 200 -Wait"
        self.console_process = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            env=environment, creationflags=0x00000010,
        )

    def _show_device_probe(self, icon=None, item=None):
        """在独立线程中打开唯一的设备管理窗口。"""
        del icon, item
        with self.device_probe_window_lock:
            if self.device_probe_window_open:
                return
            self.device_probe_window_open = True
        threading.Thread(
            target=self._run_device_probe_window_guarded,
            name="设备探测窗口",
            daemon=True,
        ).start()

    def _run_device_probe_window_guarded(self):
        """运行设备管理窗口，并在窗口退出后恢复可打开状态。"""
        try:
            self._run_device_probe_window()
        except Exception as error:
            LOGGER.exception("打开设备探测窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开设备探测窗口，请查看日志", APPLICATION_NAME)
        finally:
            with self.device_probe_window_lock:
                self.device_probe_window_open = False

    def _run_device_probe_window(self):
        """展示已连接设备信息，并提供带等待进度的设备重启操作。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("设备管理")
        root.geometry("720x520")
        root.minsize(560, 320)
        root.attributes("-topmost", True)
        self._set_tk_window_icon(root)

        status = tk.StringVar(value="正在探测 Pico LCD 设备，请稍候……")
        ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        progress = ttk.Progressbar(root, mode="indeterminate")
        progress.pack(fill=tk.X, padx=16, pady=(0, 12))
        progress.start(12)

        device_panel = ttk.LabelFrame(root, text="当前已连接设备", padding=12)
        device_panel.pack(fill=tk.X, padx=16, pady=(0, 12))
        device_values = {
            "Pico 开发板型号": tk.StringVar(value="未连接"),
            "Pico 屏幕色彩方案": tk.StringVar(value="--"),
            "Pico 固件版本": tk.StringVar(value="--"),
            "Pico 屏幕分辨率": tk.StringVar(value="--"),
        }
        for row, (label, value) in enumerate(device_values.items()):
            ttk.Label(device_panel, text=label + "：", width=20).grid(
                row=row, column=0, sticky=tk.W, pady=2
            )
            ttk.Label(device_panel, textvariable=value).grid(
                row=row, column=1, sticky=tk.W, pady=2
            )

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, padx=16, pady=(0, 12))
        probe_button = ttk.Button(action_frame, text="主动探测")
        probe_button.pack(side=tk.LEFT)
        reboot_button = ttk.Button(action_frame, text="重启设备", state=tk.DISABLED)
        reboot_button.pack(side=tk.RIGHT)

        log_frame = ttk.Frame(root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Microsoft YaHei UI", 9),
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_text.yview)
        log_text.configure(yscrollcommand=scrollbar.set)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        messages = queue.Queue()
        reboot_state = {"started": None}

        def clear_connected_device():
            """清空已连接设备信息，并禁用依赖有效串口的重启操作。"""
            device_values["Pico 开发板型号"].set("未连接")
            device_values["Pico 屏幕色彩方案"].set("--")
            device_values["Pico 固件版本"].set("--")
            device_values["Pico 屏幕分辨率"].set("--")
            reboot_button.configure(state=tk.DISABLED)

        def refresh_connection_state():
            """消费后台串口状态事件，实时同步设备面板和操作按钮。"""
            try:
                while True:
                    connection = self.device_connection_messages.get_nowait()
                    if not connection.get("connected"):
                        clear_connected_device()
                        status.set("当前没有已连接设备")
                        continue
                    device_values["Pico 开发板型号"].set(
                        connection.get("board_model") or "未知"
                    )
                    device_values["Pico 屏幕色彩方案"].set(
                        connection.get("screen_color_profile") or "未知"
                    )
                    device_values["Pico 固件版本"].set(
                        connection.get("firmware_version") or "未知"
                    )
                    device_values["Pico 屏幕分辨率"].set(
                        connection.get("screen_resolution") or "未知"
                    )
                    reboot_button.configure(state=tk.NORMAL)
                    status.set("设备已连接")
            except queue.Empty:
                pass
            if root.winfo_exists():
                root.after(100, refresh_connection_state)

        def append_log(content):
            """向只读文本域追加日志，并自动滚动到最新内容。"""
            log_text.configure(state=tk.NORMAL)
            log_text.insert(tk.END, content)
            log_text.see(tk.END)
            log_text.configure(state=tk.DISABLED)

        def refresh_messages():
            """消费探测线程消息，并更新进度条及最终状态。"""
            try:
                while True:
                    message_type, content = messages.get_nowait()
                    if message_type == "log":
                        append_log(content)
                        normalized = content.strip()
                        for label, value in device_values.items():
                            prefix = label + "："
                            if normalized.startswith(prefix):
                                value.set(normalized[len(prefix):].strip() or "未知")
                    else:
                        progress.stop()
                        progress.configure(mode="determinate", maximum=100, value=100)
                        success = content == 0
                        status.set("设备信息加载完成" if success else "未探测到可用设备")
                        reboot_button.configure(state=tk.NORMAL if success else tk.DISABLED)
                        probe_button.configure(state=tk.NORMAL)
                        if not success:
                            clear_connected_device()
            except queue.Empty:
                pass
            if root.winfo_exists():
                root.after(100, refresh_messages)

        def refresh_reboot_progress():
            """刷新重启等待进度，并处理设备确认或三十秒超时。"""
            started = reboot_state["started"]
            if started is None:
                return
            try:
                result = self.device_management_messages.get_nowait()
            except queue.Empty:
                result = None
            elapsed = (datetime.now() - started).total_seconds()
            if result is not None:
                reboot_state["started"] = None
                progress.stop()
                progress.configure(mode="determinate", maximum=100, value=100)
                status.set(result.get("message") or "设备已回复")
                append_log((result.get("message") or "设备已回复") + "\n")
                clear_connected_device()
                if not self.stopping.is_set():
                    process = self.worker_process
                    if process is not None and process.poll() is None:
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    self._start_worker()
                return
            if elapsed >= 30:
                reboot_state["started"] = None
                progress.configure(value=30)
                status.set("设备无响应，请重新拔插设备注册")
                append_log("设备无响应，请重新拔插设备注册\n")
                reboot_button.configure(state=tk.NORMAL)
                if not self.stopping.is_set():
                    threading.Thread(
                        target=self._restart_worker,
                        name="设备重启超时恢复",
                        daemon=True,
                    ).start()
                return
            progress.configure(value=elapsed)
            root.after(100, refresh_reboot_progress)

        def reboot_device():
            """向后台 Monitor 发送重启指令并启动三十秒响应等待。"""
            process = self.worker_process
            if process is None or process.poll() is not None or process.stdin is None:
                status.set("当前没有已连接设备")
                return
            while not self.device_management_messages.empty():
                self.device_management_messages.get_nowait()
            try:
                process.stdin.write("EXIT_REBOOT\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                status.set("重启指令发送失败")
                return
            reboot_button.configure(state=tk.DISABLED)
            progress.stop()
            progress.configure(mode="determinate", maximum=30, value=0)
            status.set("重启指令已发送，正在等待设备回复……")
            append_log("重启指令已发送，最长等待 30 秒。\n")
            reboot_state["started"] = datetime.now()
            refresh_reboot_progress()

        reboot_button.configure(command=reboot_device)

        def perform_probe():
            """暂停常驻监控，执行单次设备探测并在结束后恢复监控。"""
            worker_process = self.worker_process
            if worker_process is not None and worker_process.poll() is None:
                messages.put(("log", "检测到当前设备连接，正在断开……\n"))
                self._stop_worker()
                messages.put(("log", "当前设备连接已断开，开始重新探测。\n"))
            else:
                messages.put(("log", "当前没有已连接设备，开始探测。\n"))
            self.worker_process = None
            process = None
            try:
                process = subprocess.Popen(
                    self._device_probe_command(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=0x08000000,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                )
                for line in process.stdout:
                    messages.put(("log", line))
                messages.put(("done", process.wait()))
            except OSError as error:
                messages.put(("log", "启动设备探测失败：{}\n".format(error)))
                messages.put(("done", 1))
            finally:
                if not self.stopping.is_set():
                    self._start_worker()

        def start_probe():
            """启动主动设备探测线程，避免阻塞设备管理窗口。"""
            probe_button.configure(state=tk.DISABLED)
            reboot_button.configure(state=tk.DISABLED)
            status.set("正在主动探测 Pico LCD 设备，请稍候……")
            progress.configure(mode="indeterminate")
            progress.start(12)
            device_values["Pico 开发板型号"].set("探测中……")
            device_values["Pico 屏幕色彩方案"].set("--")
            device_values["Pico 固件版本"].set("--")
            device_values["Pico 屏幕分辨率"].set("--")
            threading.Thread(
                target=perform_probe,
                name="设备主动探测",
                daemon=True,
            ).start()

        probe_button.configure(command=start_probe)
        start_probe()
        refresh_messages()
        refresh_connection_state()
        self._center_tk_window(root)
        root.mainloop()

    @staticmethod
    def _remove_incomplete_utf8_prefix(content):
        """移除日志片段开头不完整的 UTF-8 字符，避免中文内容乱码。"""
        for offset in range(min(4, len(content) + 1)):
            try:
                content[offset:].decode("utf-8")
                return content[offset:]
            except UnicodeDecodeError as error:
                if error.start > 0:
                    return content[offset:]
        return content

    def _read_recent_log(self, maximum_size=LOG_EXPORT_SIZE):
        """读取日志末尾指定字节数，并修正可能被截断的 UTF-8 字符。"""
        if not self.log_path.exists():
            return b""
        with self.log_path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            file_size = log_file.tell()
            log_file.seek(max(0, file_size - maximum_size))
            content = log_file.read(maximum_size)
        return self._remove_incomplete_utf8_prefix(content)

    def _export_log(self, icon=None, item=None):
        """导出最近一兆字节日志，并在资源管理器中打开导出文件目录。"""
        del item
        export_directory = self.data_directory / "exports"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        export_path = export_directory / "pico-monitor-{}.log".format(timestamp)
        try:
            export_directory.mkdir(parents=True, exist_ok=True)
            export_path.write_bytes(self._read_recent_log())
            subprocess.Popen(
                ["explorer.exe", "/select,", str(export_path)],
                creationflags=0x08000000,
            )
            if icon is not None:
                icon.notify("日志已导出：{}".format(export_path.name), APPLICATION_NAME)
        except OSError as error:
            if icon is not None:
                icon.notify("日志导出失败：{}".format(error), APPLICATION_NAME)

    @staticmethod
    def _autostart_command():
        if getattr(sys, "frozen", False):
            return '"{}"'.format(Path(sys.executable).resolve())
        return '"{}" "{}"'.format(sys.executable, MONITOR_DIRECTORY / "pico_monitor.py")

    @staticmethod
    def _is_autostart(item=None):
        del item
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return value == WindowsTrayApplication._autostart_command()
        except OSError:
            return False

    def _toggle_autostart(self, icon, item):
        del item
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if self._is_autostart():
                winreg.DeleteValue(key, AUTOSTART_NAME)
            else:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, self._autostart_command())
        icon.update_menu()

    def _is_dev_mode(self, item=None):
        """返回托盘配置中的开发模式开关状态。"""
        del item
        return bool(self.settings.get("dev"))

    def _toggle_dev_mode(self, icon, item):
        """切换开发模式并重启后台监控进程，使新配置立即生效。"""
        del item
        self.settings["dev"] = not self._is_dev_mode()
        self.settings_store.save(self.settings)
        self._restart_worker()
        icon.update_menu()
        state = "开启" if self.settings["dev"] else "关闭"
        icon.notify("开发模式已{}".format(state), APPLICATION_NAME)

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
        """在工作线程中运行 Tk 消息循环，确认地址后继续执行更新。"""
        handoff_to_updater = False
        try:
            update_url = self._ask_update_url()
            if update_url is None:
                return
            self.settings["update_url"] = update_url
            self.settings_store.save(self.settings)
            handoff_to_updater = True
        except Exception as error:
            LOGGER.exception("打开更新地址窗口失败：%s", error)
            icon.notify("无法打开更新地址窗口，请查看日志", APPLICATION_NAME)
            return
        finally:
            if not handoff_to_updater:
                self.update_lock.release()
        self._perform_update(icon, update_url)

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
        """下载最新 Release，先升级 Pico，再安排替换 Monitor。"""
        updater = WindowsReleaseUpdater(GITHUB_REPOSITORY, MONITOR_VERSION)
        monitor_path = None
        pico_path = None
        try:
            icon.notify("正在检查最新版本", APPLICATION_NAME)
            latest_version, assets = updater.latest_release(update_url)
            if not updater.update_available(latest_version):
                icon.notify("当前已是最新版本：{}".format(MONITOR_VERSION), APPLICATION_NAME)
                return
            pico_asset = updater.select_pico_asset(assets, latest_version)
            monitor_asset = updater.select_monitor_asset(assets)
            icon.notify("发现版本 {}，正在下载更新".format(latest_version), APPLICATION_NAME)
            pico_path = updater.download(pico_asset, ".zip")
            monitor_path = updater.download(monitor_asset, ".exe")
            self._stop_worker()
            self._upgrade_pico_from_package(pico_path)
            updater.remove_file(pico_path)
            pico_path = None
            self._schedule_monitor_replacement(monitor_path)
            monitor_path = None
            self.stopping.set()
            icon.notify("Pico 更新完成，Monitor 即将重启", APPLICATION_NAME)
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
            message = (result.stdout or result.stderr or "Pico 升级进程异常退出").strip()
            raise RuntimeError(message[-500:])

    @staticmethod
    def _schedule_monitor_replacement(download_path):
        """由独立 PowerShell 进程等待托盘退出后替换 EXE 并重新启动。"""
        target_path = Path(sys.executable).resolve()
        environment = os.environ.copy()
        environment.update({
            "PICO_UPDATE_PID": str(os.getpid()),
            "PICO_UPDATE_SOURCE": str(Path(download_path).resolve()),
            "PICO_UPDATE_TARGET": str(target_path),
        })
        command = (
            "Wait-Process -Id $env:PICO_UPDATE_PID -ErrorAction SilentlyContinue;"
            "Copy-Item -LiteralPath $env:PICO_UPDATE_SOURCE -Destination $env:PICO_UPDATE_TARGET -Force;"
            "Start-Process -FilePath $env:PICO_UPDATE_TARGET;"
            "Remove-Item -LiteralPath $env:PICO_UPDATE_SOURCE -Force -ErrorAction SilentlyContinue"
        )
        subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            env=environment,
            creationflags=0x08000000,
        )

    def _select_style(self, style):
        def select(icon, item):
            del item
            self.settings["lcd_style"] = style
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
            icon.notify("已切换为{}".format(style_names(self.settings)[style]), APPLICATION_NAME)
        return select

    def _style_checked(self, style):
        return lambda item: self.settings["lcd_style"] == style

    def _show_settings(self, icon=None, item=None):
        del item
        with self.settings_window_lock:
            if self.settings_window_open:
                self.settings_window_restore_requested.set()
                return
            # 在创建线程前占位，避免连续点击同时创建多个 Tk 窗口。
            self.settings_window_restore_requested.clear()
            self.settings_window_open = True
        threading.Thread(
            target=self._run_settings_window_guarded,
            name="配置窗口",
            daemon=True,
        ).start()

    def _show_about(self, icon=None, item=None):
        """在独立线程中打开唯一的关于应用窗口。"""
        del icon, item
        with self.about_window_lock:
            if self.about_window_open:
                return
            self.about_window_open = True
        threading.Thread(
            target=self._run_about_window_guarded,
            name="关于应用窗口",
            daemon=True,
        ).start()

    def _run_about_window_guarded(self):
        """运行关于窗口，并在窗口退出后恢复可打开状态。"""
        try:
            self._run_about_window()
        except Exception as error:
            LOGGER.exception("打开关于应用窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开关于应用窗口，请查看日志", APPLICATION_NAME)
        finally:
            with self.about_window_lock:
                self.about_window_open = False

    def _run_about_window(self):
        """显示版本、作者、联系方式和店铺二维码。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.title("关于应用")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        self._set_tk_window_icon(root)
        frame = tk.Frame(root, padx=24, pady=18)
        frame.pack()
        tk.Label(frame, text=APPLICATION_NAME, font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(0, 8))
        tk.Label(frame, text="版本号：{}".format(MONITOR_VERSION)).pack(anchor="w", pady=2)
        tk.Label(frame, text="作者：tokyohost").pack(anchor="w", pady=2)
        tk.Label(frame, text="微信号：hi2024FL").pack(anchor="w", pady=2)
        tk.Label(frame, text="咸鱼店铺二维码：").pack(anchor="w", pady=(10, 4))
        image_path = self._resource_path("assert", "fishQr.png")
        with Image.open(image_path) as source:
            qr_image = source.convert("RGB").resize((220, 220), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(qr_image)
        image_label = tk.Label(frame, image=photo)
        image_label.image = photo
        image_label.pack()
        tk.Button(frame, text="确定", width=12, command=root.destroy).pack(pady=(14, 0))
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        self._center_tk_window(root)
        root.mainloop()

    def _run_settings_window_guarded(self):
        try:
            self._run_settings_window()
        finally:
            self.settings_window = None
            with self.settings_window_lock:
                self.settings_window_open = False

    @staticmethod
    def _configure_tk_runtime():
        """为源码运行和单文件运行配置 Tcl/Tk 标准库路径。"""
        python_root = Path(sys.base_prefix)
        tcl_dir = python_root / "tcl" / "tcl8.6"
        tk_dir = python_root / "tcl" / "tk8.6"

        if (tcl_dir / "init.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)

        if (tk_dir / "tk.tcl").exists():
            os.environ["TK_LIBRARY"] = str(tk_dir)

    @staticmethod
    def _center_tk_window(window):
        """将 Tk 窗口固定放置在屏幕中央。"""
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        if width <= 1:
            width = window.winfo_reqwidth()
        if height <= 1:
            height = window.winfo_reqheight()
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 2)
        window.geometry("{}x{}+{}+{}".format(width, height, x, y))

    def _set_tk_window_icon(self, window):
        """为当前窗口及其后续弹框统一设置托盘程序图标。"""
        import tkinter as tk

        application_icon = tk.PhotoImage(
            master=window,
            file=self._resource_path("icon", "icon.png"),
        )
        window.iconphoto(True, application_icon)
        window.application_icon = application_icon

    def _run_settings_window(self):
        """使用原生控件绘制接近 Element Plus 的分组配置对话框。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        self.settings_window = root
        root.title("Pico Monitor 配置")
        self._set_tk_window_icon(root)
        root.geometry("680x700")
        root.minsize(620, 620)
        root.configure(bg="#f5f7fa")
        root.option_add("*Font", ("Microsoft YaHei UI", 10))

        def restore_when_requested():
            if self.settings_window_restore_requested.is_set():
                self.settings_window_restore_requested.clear()
                root.deiconify()
                root.lift()
                root.focus_force()
            root.after(100, restore_when_requested)

        root.after(100, restore_when_requested)
        style = ttk.Style(root)
        style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"), foreground="#303133", background="#f5f7fa")
        style.configure("Hint.TLabel", foreground="#909399", background="#f5f7fa")
        style.configure("Card.TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 11, "bold"), foreground="#303133", background="#ffffff")
        style.configure("Card.TLabel", foreground="#606266", background="#ffffff")
        style.configure("Primary.TButton", foreground="#ffffff", background="#409eff", padding=(18, 8))
        style.configure("Footer.TButton", foreground="#303133", padding=(18, 8))

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        content_area = ttk.Frame(root)
        content_area.grid(row=0, column=0, sticky="nsew")
        content_area.rowconfigure(0, weight=1)
        content_area.columnconfigure(0, weight=1)

        canvas = tk.Canvas(content_area, bg="#f5f7fa", highlightthickness=0)
        scrollbar = ttk.Scrollbar(content_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        body = ttk.Frame(canvas, padding=24)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")

        def update_scroll_region(event=None):
            del event
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_scroll_body(event):
            canvas.itemconfigure(body_window, width=event.width)

        def scroll_with_mouse(event):
            if event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        body.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_scroll_body)
        root.bind("<MouseWheel>", scroll_with_mouse)

        ttk.Label(body, text="配置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="显示设置可即时应用，其他配置保存后会重启监控服务", style="Hint.TLabel").pack(anchor="w", pady=(2, 18))

        variables = {
            "port": tk.StringVar(value=self.settings["port"]),
            "ping_target": tk.StringVar(value=self.settings["ping_target"]),
            "interval": tk.StringVar(value=self.settings["interval"]),
            "reconnect_interval": tk.StringVar(value=self.settings["reconnect_interval"]),
            "serial_probe_interval": tk.StringVar(value=self.settings["serial_probe_interval"]),
            "screen_rotation": tk.StringVar(value=str(self.settings["screen_rotation"])),
            "lcd_brightness": tk.IntVar(value=self.settings["lcd_brightness"]),
            "network_unit": tk.StringVar(value=self.settings["network_unit"]),
            "lcd_style": tk.StringVar(
                value=style_label(self.settings["lcd_style"], self.settings)
            ),
            "qbittorrent_enabled": tk.BooleanVar(value=False),
            "qbittorrent_address": tk.StringVar(value=self.settings["qbittorrent_address"]),
            "qbittorrent_username": tk.StringVar(value=self.settings["qbittorrent_username"]),
            "qbittorrent_password": tk.StringVar(value=self.settings["qbittorrent_password"]),
            "qbittorrent_interval": tk.StringVar(value=self.settings["qbittorrent_interval"]),
        }

        def card(title):
            frame = ttk.LabelFrame(body, text=title, style="Card.TLabelframe", padding=16)
            frame.pack(fill="x", pady=(0, 14))
            frame.columnconfigure(1, weight=1)
            return frame

        def field(parent, row, label, widget):
            ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)
            widget.grid(row=row, column=1, sticky="ew", pady=6)

        display = card("显示设置")
        styles = [style_label(name, self.settings) for name in style_names(self.settings)]
        field(display, 0, "界面样式", ttk.Combobox(display, textvariable=variables["lcd_style"], values=styles, state="readonly"))
        field(display, 1, "屏幕旋转", ttk.Combobox(display, textvariable=variables["screen_rotation"], values=("0", "180"), state="readonly"))
        brightness_control = ttk.Frame(display)
        brightness_control.columnconfigure(0, weight=1)
        brightness_slider = tk.Scale(
            brightness_control,
            variable=variables["lcd_brightness"],
            from_=1,
            to=100,
            orient="horizontal",
            showvalue=True,
            resolution=1,
            bg="#ffffff",
            highlightthickness=0,
        )
        brightness_slider.grid(row=0, column=0, sticky="ew")
        field(display, 2, "背光亮度（1-100%）", brightness_control)
        field(display, 3, "网络速率单位", ttk.Combobox(display, textvariable=variables["network_unit"], values=("MB", "Mbps"), state="readonly"))

        def save_display_settings():
            """保存显示设置并通知运行中的 Monitor 在下一帧应用。"""
            try:
                selected_style = next(
                    name for name in style_names(self.settings)
                    if style_label(name, self.settings) == variables["lcd_style"].get()
                )
                brightness = int(variables["lcd_brightness"].get())
                if not 1 <= brightness <= 100:
                    raise ValueError
            except (ValueError, StopIteration):
                messagebox.showerror("配置错误", "背光亮度必须为 1 至 100。", parent=root)
                return
            self.settings.update({
                "lcd_style": selected_style,
                "screen_rotation": int(variables["screen_rotation"].get()),
                "lcd_brightness": brightness,
                "network_unit": variables["network_unit"].get(),
            })
            self.settings_store.save(self.settings)
            if not self._apply_display_settings():
                messagebox.showerror("应用失败", "Monitor 未运行，显示设置暂未应用。", parent=root)
                return
            if self.icon is not None:
                self.icon.update_menu()
                self.icon.notify("显示设置已保存并即时应用", APPLICATION_NAME)

        ttk.Button(
            display,
            text="保存并应用",
            command=save_display_settings,
            width=14,
        ).grid(row=4, column=1, sticky="e", pady=(10, 0))

        monitor = card("监控连接")
        port_control = ttk.Frame(monitor)
        port_control.columnconfigure(0, weight=1)
        ttk.Entry(port_control, textvariable=variables["port"]).grid(row=0, column=0, sticky="ew")

        def save_port():
            self.settings["port"] = variables["port"].get().strip()
            self.settings_store.save(self.settings)
            self._restart_worker()
            if self.icon is not None:
                self.icon.notify(
                    "串口已保存：{}；Monitor 已重启".format(
                        self.settings["port"] or "自动发现"
                    ),
                    APPLICATION_NAME,
                )

        ttk.Button(port_control, text="保存", command=save_port).grid(
            row=0, column=1, padx=(8, 0)
        )
        field(monitor, 0, "串口（留空自动发现）", port_control)
        field(monitor, 1, "Ping 目标", ttk.Entry(monitor, textvariable=variables["ping_target"]))
        field(monitor, 2, "采集间隔（秒）", ttk.Entry(monitor, textvariable=variables["interval"]))
        field(monitor, 3, "重连间隔（秒）", ttk.Entry(monitor, textvariable=variables["reconnect_interval"]))
        field(monitor, 4, "串口探测 PING 间隔（秒）", ttk.Entry(monitor, textvariable=variables["serial_probe_interval"]))

        qb = card("qBittorrent")
        enable_qbittorrent = ttk.Checkbutton(
            qb,
            text="启用 qBittorrent 指标采集（请先验证账号密码）",
            variable=variables["qbittorrent_enabled"],
            state="disabled",
        )
        enable_qbittorrent.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        field(qb, 1, "Web UI 地址", ttk.Entry(qb, textvariable=variables["qbittorrent_address"]))
        field(qb, 2, "用户名", ttk.Entry(qb, textvariable=variables["qbittorrent_username"]))
        field(qb, 3, "密码", ttk.Entry(qb, textvariable=variables["qbittorrent_password"], show="●"))
        field(qb, 4, "采集间隔（秒）", ttk.Entry(qb, textvariable=variables["qbittorrent_interval"]))

        verified_qbittorrent_credentials = [None]
        verification_results = queue.Queue()
        verification_button = ttk.Button(qb, text="验证账号密码", width=14)
        verification_button.grid(row=5, column=1, sticky="e", pady=(6, 0))

        def current_qbittorrent_credentials():
            return (
                variables["qbittorrent_address"].get().strip(),
                variables["qbittorrent_username"].get().strip(),
                variables["qbittorrent_password"].get(),
            )

        def invalidate_qbittorrent_verification(*unused):
            del unused
            verified_qbittorrent_credentials[0] = None
            variables["qbittorrent_enabled"].set(False)
            enable_qbittorrent.configure(state="disabled")

        for name in ("qbittorrent_address", "qbittorrent_username", "qbittorrent_password"):
            variables[name].trace_add("write", invalidate_qbittorrent_verification)

        def verify_qbittorrent():
            credentials = current_qbittorrent_credentials()
            if not all(credentials):
                messagebox.showerror("验证失败", "请先填写 Web UI 地址、用户名和密码。", parent=root)
                return
            verification_button.configure(state="disabled", text="正在验证...")
            enable_qbittorrent.configure(state="disabled")
            variables["qbittorrent_enabled"].set(False)

            def run_verification():
                try:
                    QbittorrentApiClient(*credentials).login()
                    verification_results.put((credentials, None))
                except Exception as error:  # 网络和认证错误均反馈到配置页。
                    verification_results.put((credentials, str(error)))

            threading.Thread(target=run_verification, name="qBittorrent 账号验证", daemon=True).start()

        verification_button.configure(command=verify_qbittorrent)

        def consume_verification_result():
            try:
                credentials, error = verification_results.get_nowait()
            except queue.Empty:
                root.after(100, consume_verification_result)
                return
            verification_button.configure(state="normal", text="验证账号密码")
            if credentials != current_qbittorrent_credentials():
                root.after(100, consume_verification_result)
                return
            if error is not None:
                messagebox.showerror("验证失败", error, parent=root)
            else:
                verified_qbittorrent_credentials[0] = credentials
                enable_qbittorrent.configure(state="normal")
                messagebox.showinfo("验证成功", "qBittorrent 账号密码验证成功，现在可以启用指标采集。", parent=root)
            root.after(100, consume_verification_result)

        root.after(100, consume_verification_result)

        def save():
            try:
                selected_style = next(name for name in style_names(self.settings) if style_label(name, self.settings) == variables["lcd_style"].get())
                updated = {
                    "port": variables["port"].get().strip(),
                    "ping_target": variables["ping_target"].get().strip(),
                    "interval": float(variables["interval"].get()),
                    "reconnect_interval": float(variables["reconnect_interval"].get()),
                    "serial_probe_interval": float(variables["serial_probe_interval"].get()),
                    "screen_rotation": int(variables["screen_rotation"].get()),
                    "lcd_brightness": int(variables["lcd_brightness"].get()),
                    "network_unit": variables["network_unit"].get(),
                    "lcd_style": selected_style,
                    "qbittorrent_enabled": variables["qbittorrent_enabled"].get(),
                    "qbittorrent_address": variables["qbittorrent_address"].get().strip(),
                    "qbittorrent_username": variables["qbittorrent_username"].get().strip(),
                    "qbittorrent_password": variables["qbittorrent_password"].get(),
                    "qbittorrent_interval": float(variables["qbittorrent_interval"].get()),
                }
                if (not updated["ping_target"]
                        or min(updated["interval"], updated["reconnect_interval"], updated["serial_probe_interval"], updated["qbittorrent_interval"]) <= 0
                        or not 1 <= updated["lcd_brightness"] <= 100):
                    raise ValueError
                if updated["qbittorrent_enabled"] and not all((updated["qbittorrent_address"], updated["qbittorrent_username"], updated["qbittorrent_password"])):
                    messagebox.showerror("配置错误", "启用 qBittorrent 后，请填写地址、用户名和密码。", parent=root)
                    return
                if updated["qbittorrent_enabled"] and current_qbittorrent_credentials() != verified_qbittorrent_credentials[0]:
                    messagebox.showerror("配置错误", "请先验证 qBittorrent 账号密码，验证成功后才能启用指标采集。", parent=root)
                    return
            except (ValueError, StopIteration):
                messagebox.showerror("配置错误", "请检查地址和时间间隔，时间间隔必须大于 0。", parent=root)
                return
            self.settings = updated
            self.settings_store.save(updated)
            self._restart_worker()
            if self.icon is not None:
                self.icon.update_menu()
                self.icon.notify("配置已保存并生效", APPLICATION_NAME)
            root.destroy()

        buttons = ttk.Frame(root, padding=(24, 12))
        buttons.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            buttons,
            text="取消",
            command=root.destroy,
            width=12,
            style="Footer.TButton",
        ).pack(side="right")
        ttk.Button(
            buttons,
            text="保存配置",
            command=save,
            width=12,
            style="Footer.TButton",
        ).pack(side="right", padx=(0, 10))

        def closed():
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", closed)
        self._center_tk_window(root)
        root.mainloop()

    def _exit(self, icon, item):
        """退出 Windows Monitor，不向 Pico 发送重启指令。"""
        del item
        self.stopping.set()
        self._stop_worker()
        if self.console_process is not None and self.console_process.poll() is None:
            self.console_process.terminate()
        icon.stop()

    @staticmethod
    def _create_image():
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
            pystray.MenuItem("屏幕旋转", pystray.Menu(
                pystray.MenuItem("0°", self._set_rotation(0), checked=lambda item: self.settings["screen_rotation"] == 0, radio=True),
                pystray.MenuItem("180°", self._set_rotation(180), checked=lambda item: self.settings["screen_rotation"] == 180, radio=True),
            )),
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

    def _reload_style_catalog(self):
        """从配置文件同步 Pico 样式清单及当前选择。"""
        latest_settings = self.settings_store.load()
        self.settings["styles"] = latest_settings["styles"]
        self.settings["lcd_style"] = latest_settings["lcd_style"]

    def _style_menu_items(self):
        """生成最新的样式菜单项，避免托盘长期持有启动时的静态清单。"""
        import pystray

        self._reload_style_catalog()
        return tuple(
            pystray.MenuItem(style_label(name, self.settings), self._select_style(name), checked=self._style_checked(name), radio=True)
            for name in style_names(self.settings)
        )

    def _set_rotation(self, rotation):
        def select(icon, item):
            del item
            self.settings["screen_rotation"] = rotation
            self.settings_store.save(self.settings)
            self._apply_display_settings()
            icon.update_menu()
        return select

    def run(self):
        """配置 Windows 应用标识并启动后台工作进程与托盘消息循环。"""
        import pystray

        self._configure_windows_taskbar()
        if not self._acquire_single_instance():
            return 0
        self._start_worker()
        self.icon = pystray.Icon("pico-monitor", self._create_image(), APPLICATION_NAME, self._build_menu())
        self.icon.run()
        return 0
