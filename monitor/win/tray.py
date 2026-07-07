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
import traceback
import winreg
from datetime import datetime
from pathlib import Path

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
import custom_data
from qbittorrent_monitor import QbittorrentApiClient
from windows_update import WindowsReleaseUpdater

from .settings import (
    DEFAULT_SETTINGS,
    TraySettingsStore,
    apply_worker_arguments,
    normalize_style_catalog,
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
        self.device_connection_messages = queue.Queue()
        self.device_connection_lock = threading.Lock()
        self.current_device_connection = {"connected": False}
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
        environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
        environment["PICO_MONITOR_SETTINGS_PATH"] = str(self.settings_store.path)
        environment["PICO_MONITOR_SCREENSHOT_DIR"] = str(self.screenshot_directory)
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
                if self.custom_style_upload_active.is_set():
                    self.custom_style_upload_logs.put(line.rstrip("\r\n"))
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
                if line.startswith("CUSTOM_STYLE_LIST_RESULT:"):
                    try:
                        result = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        result = {"status": "error", "message": "设备返回了无效响应"}
                    self.custom_style_messages.put(result)
                if line.startswith("CUSTOM_STYLE_UPLOAD_RESULT:"):
                    try:
                        result = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        result = {"status": "error", "message": "设备返回了无效响应"}
                    self.custom_style_upload_messages.put(result)
                    self.custom_style_upload_active.clear()
                if line.startswith("CUSTOM_STYLE_DELETE_RESULT:"):
                    try:
                        result = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        result = {"status": "error", "message": "设备返回了无效响应"}
                    self.custom_style_delete_messages.put(result)
                if line.startswith("SCREENSHOT_RESULT:"):
                    try:
                        result = json.loads(line.split(":", 1)[1])
                    except json.JSONDecodeError:
                        result = {"status": "error", "message": "设备返回了无效截图响应"}
                    self._handle_screenshot_result(result)
                if "[串口关闭]" in line or "监控通信异常：" in line:
                    self._update_device_connection({"connected": False})
                connection = re.search(
                    r"\[串口连接\].*握手成功：开发板=(.*)，屏幕方案=(.*)，固件版本=(.*)，分辨率=(.*)$",
                    line.strip(),
                )
                if connection:
                    self._update_device_connection({
                        "connected": True,
                        "board_model": connection.group(1),
                        "screen_color_profile": connection.group(2),
                        "firmware_version": connection.group(3),
                        "screen_resolution": connection.group(4),
                    })
        return_code = process.wait()
        if not self.stopping.is_set() and process is self.worker_process and self.icon is not None:
            self.icon.notify("后台监控已退出，返回码：{}".format(return_code), APPLICATION_NAME)

    def _update_device_connection(self, connection):
        """保存最新设备连接快照，并通知已打开的设备管理窗口。"""
        snapshot = dict(connection)
        with self.device_connection_lock:
            self.current_device_connection = snapshot
        self.device_connection_messages.put(snapshot)

    def _handle_screenshot_result(self, result):
        """提示截图结果，并在成功时打开截图目录。"""
        if result.get("status") != "ok":
            if self.icon is not None:
                self.icon.notify(
                    "屏幕截图失败：{}".format(result.get("message", "未知错误")),
                    APPLICATION_NAME,
                )
            return
        path = Path(result["path"])
        try:
            subprocess.Popen(["explorer", str(path.parent)])
        except OSError as error:
            LOGGER.warning("打开截图目录失败：%s", error)
        if self.icon is not None:
            self.icon.notify("屏幕截图已保存：{}".format(path.name), APPLICATION_NAME)

    def _take_screenshot(self, icon=None, item=None):
        """通知 Monitor 工作进程向 Pico 下发 screenshot 命令。"""
        del item
        process = self.worker_process
        if process is None or process.poll() is not None or process.stdin is None:
            if icon is not None:
                icon.notify("后台监控未运行，无法截图", APPLICATION_NAME)
            return
        try:
            process.stdin.write("SCREENSHOT\n")
            process.stdin.flush()
            if icon is not None:
                icon.notify("正在截取 LCD 屏幕", APPLICATION_NAME)
        except (BrokenPipeError, OSError) as error:
            if icon is not None:
                icon.notify("截图请求失败：{}".format(error), APPLICATION_NAME)

    def _get_device_connection(self):
        """返回当前设备连接状态的独立快照。"""
        with self.device_connection_lock:
            return dict(self.current_device_connection)

    def _show_log(self, icon=None, item=None):
        """在应用内打开唯一的实时日志查看窗口。"""
        del icon, item
        with self.log_window_lock:
            if self.log_window_open:
                return
            self.log_window_open = True
        threading.Thread(
            target=self._run_log_window_guarded,
            name="日志窗口",
            daemon=True,
        ).start()

    def _run_log_window_guarded(self):
        """运行日志窗口，并在关闭后恢复窗口可打开状态。"""
        try:
            self._run_log_window()
        except Exception as error:
            LOGGER.exception("打开日志窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开日志窗口，请稍后重试", APPLICATION_NAME)
        finally:
            with self.log_window_lock:
                self.log_window_open = False

    def _run_log_window(self):
        """创建支持复制、自动刷新和导出的日志文本窗口。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.title("系统监控日志")
        root.geometry("900x600")
        root.minsize(620, 380)
        self._set_tk_window_icon(root)

        status = tk.StringVar(master=root, value="正在加载日志……")
        ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        text_frame = ttk.Frame(root)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        log_text = tk.Text(
            text_frame,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        vertical_scrollbar = ttk.Scrollbar(
            text_frame,
            orient=tk.VERTICAL,
            command=log_text.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            text_frame,
            orient=tk.HORIZONTAL,
            command=log_text.xview,
        )
        log_text.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        log_text.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        state = {"content": None}

        def refresh_log():
            """读取最近日志，并在用户位于末尾时保持自动滚动。"""
            content = self._read_recent_log().decode("utf-8", errors="replace")
            if content != state["content"]:
                at_end = log_text.yview()[1] >= 0.999
                log_text.configure(state=tk.NORMAL)
                log_text.delete("1.0", tk.END)
                log_text.insert("1.0", content)
                log_text.configure(state=tk.DISABLED)
                if at_end or state["content"] is None:
                    log_text.see(tk.END)
                state["content"] = content
                status.set("已加载最近 {:,} 字节日志".format(len(content.encode("utf-8"))))
            if root.winfo_exists():
                root.after(1000, refresh_log)

        def copy_all():
            """把当前文本域中的全部日志复制到系统剪贴板。"""
            root.clipboard_clear()
            root.clipboard_append(log_text.get("1.0", "end-1c"))
            status.set("日志已复制到剪贴板")

        def export_log():
            """调用统一导出逻辑并向用户反馈结果。"""
            try:
                export_path = self._export_log()
            except OSError as error:
                messagebox.showerror("导出日志", str(error), parent=root)
                return
            status.set("日志已导出：{}".format(export_path.name))

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(action_frame, text="复制全部", command=copy_all).pack(side=tk.LEFT)
        ttk.Button(action_frame, text="导出日志", command=export_log).pack(side=tk.RIGHT)
        refresh_log()
        self._center_tk_window(root)
        root.mainloop()

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

        # 显式绑定当前窗口的 Tcl 解释器，避免多个独立 Tk 线程共享默认根窗口。
        status = tk.StringVar(master=root, value="正在探测 OmniWatch 设备，请稍候……")
        ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        progress = ttk.Progressbar(root, mode="indeterminate")
        progress.pack(fill=tk.X, padx=16, pady=(0, 12))
        progress.start(12)

        device_panel = ttk.LabelFrame(root, text="当前已连接设备", padding=12)
        device_panel.pack(fill=tk.X, padx=16, pady=(0, 12))
        device_labels = {
            "board_model": "开发板型号",
            "screen_color_profile": "屏幕色彩方案",
            "firmware_version": "固件版本",
            "screen_resolution": "屏幕分辨率",
        }
        device_values = {
            "board_model": tk.StringVar(master=root, value="未连接"),
            "screen_color_profile": tk.StringVar(master=root, value="--"),
            "firmware_version": tk.StringVar(master=root, value="--"),
            "screen_resolution": tk.StringVar(master=root, value="--"),
        }
        for row, (field_name, value) in enumerate(device_values.items()):
            ttk.Label(
                device_panel,
                text=device_labels[field_name] + "：",
                width=20,
            ).grid(
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
        initial_connection = self._get_device_connection()

        def clear_connected_device():
            """清空已连接设备信息，并禁用依赖有效串口的重启操作。"""
            device_values["board_model"].set("未连接")
            device_values["screen_color_profile"].set("--")
            device_values["firmware_version"].set("--")
            device_values["screen_resolution"].set("--")
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
                    device_values["board_model"].set(
                        connection.get("board_model") or "未知"
                    )
                    device_values["screen_color_profile"].set(
                        connection.get("screen_color_profile") or "未知"
                    )
                    device_values["firmware_version"].set(
                        connection.get("firmware_version") or "未知"
                    )
                    device_values["screen_resolution"].set(
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
                        for field_name, value in device_values.items():
                            prefix = "OmniWatch " + device_labels[field_name] + "："
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

        def show_connected_device(connection):
            """将已连接设备快照显示到设备管理面板。"""
            for field_name, value in device_values.items():
                value.set(connection.get(field_name) or "未知")
            reboot_button.configure(state=tk.NORMAL)
            progress.stop()
            progress.configure(mode="determinate", maximum=100, value=100)
            status.set("设备已连接")

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
                    env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1"),
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
            status.set("正在主动探测 OmniWatch 设备，请稍候……")
            progress.configure(mode="indeterminate")
            progress.start(12)
            device_values["board_model"].set("探测中……")
            device_values["screen_color_profile"].set("--")
            device_values["firmware_version"].set("--")
            device_values["screen_resolution"].set("--")
            threading.Thread(
                target=perform_probe,
                name="设备主动探测",
                daemon=True,
            ).start()

        probe_button.configure(command=start_probe)
        if initial_connection.get("connected"):
            show_connected_device(initial_connection)
        else:
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
        """导出最近一兆字节日志，打开文件目录并返回导出路径。"""
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
            return export_path
        except OSError as error:
            if icon is not None:
                icon.notify("日志导出失败：{}".format(error), APPLICATION_NAME)
            raise

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
        """下载最新 Release，先升级 Pico，再安排运行 Monitor 安装包。"""
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
        # 显式绑定当前窗口的 Tcl 解释器，避免其他 Tk 线程创建过默认根窗口后跨线程复用。
        photo = ImageTk.PhotoImage(qr_image, master=root)
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
        roots = []
        for candidate in (
            getattr(sys, "_MEIPASS", None),
            sys.base_prefix,
            sys.prefix,
            sys.exec_prefix,
            Path(sys.executable).resolve().parent if sys.executable else None,
        ):
            if candidate:
                path = Path(candidate)
                if path not in roots:
                    roots.append(path)

        for root in roots:
            tcl_dir = root / "tcl" / "tcl8.6"
            tk_dir = root / "tcl" / "tk8.6"
            if "TCL_LIBRARY" not in os.environ and (tcl_dir / "init.tcl").exists():
                os.environ["TCL_LIBRARY"] = str(tcl_dir)
            if "TK_LIBRARY" not in os.environ and (tk_dir / "tk.tcl").exists():
                os.environ["TK_LIBRARY"] = str(tk_dir)
            if "TCL_LIBRARY" in os.environ and "TK_LIBRARY" in os.environ:
                break

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

    def _show_copyable_error_dialog(self, parent, title, message, detail=None):
        """显示带复制按钮的错误弹框，用于保留完整上传失败原因。"""
        import tkinter as tk
        from tkinter import ttk

        title_text = str(title or "错误")
        message_text = str(message or "未知错误")
        detail_text = "" if detail is None else str(detail)
        copy_text = message_text if not detail_text else "{}\n\n{}".format(
            message_text,
            detail_text,
        )

        owner = parent if parent is not None else self.settings_window
        dialog = tk.Toplevel(owner) if owner is not None else tk.Tk()
        dialog.title(title_text)
        dialog.resizable(True, True)
        dialog.configure(bg="#f5f7fa")
        dialog.geometry("620x360")
        dialog.minsize(480, 260)
        try:
            if owner is not None:
                dialog.transient(owner)
            dialog.attributes("-topmost", True)
            dialog.grab_set()
        except tk.TclError:
            pass
        try:
            self._set_tk_window_icon(dialog)
        except Exception:
            pass

        container = ttk.Frame(dialog, padding=18)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(
            container,
            text=title_text,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            container,
            text=message_text,
            foreground="#c0392b",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 8))

        text_box = tk.Text(
            container,
            height=9,
            wrap=tk.WORD,
            relief=tk.SOLID,
            borderwidth=1,
            font=("Consolas", 9),
        )
        scrollbar = ttk.Scrollbar(
            container,
            orient=tk.VERTICAL,
            command=text_box.yview,
        )
        text_box.configure(yscrollcommand=scrollbar.set)
        text_box.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
        text_box.insert("1.0", copy_text)
        text_box.configure(state=tk.DISABLED)

        action_frame = ttk.Frame(container)
        action_frame.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        copy_state = ttk.Label(action_frame, text="", foreground="#67c23a")
        copy_state.pack(side=tk.LEFT, padx=(0, 10))

        def copy_error_content():
            dialog.clipboard_clear()
            dialog.clipboard_append(copy_text)
            dialog.update()
            copy_state.configure(text="已复制")

        ttk.Button(
            action_frame,
            text="复制报错内容",
            command=copy_error_content,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            action_frame,
            text="关闭",
            command=dialog.destroy,
        ).pack(side=tk.LEFT)

        dialog.bind("<Escape>", lambda event: dialog.destroy())
        self._center_tk_window(dialog)
        dialog.focus_force()
        dialog.wait_window()

    def _report_unhandled_crash(
        self,
        exception_type,
        exception,
        traceback_object,
        thread_name="托盘主线程",
    ):
        """保存未捕获异常，并显示能够复制完整堆栈的崩溃弹框。"""
        report = "".join(traceback.format_exception(
            exception_type,
            exception,
            traceback_object,
        ))
        crash_directory = self.data_directory / "crash"
        crash_path = crash_directory / datetime.now().strftime(
            "crash_%Y%m%d_%H%M%S_%f.log"
        )
        try:
            crash_directory.mkdir(parents=True, exist_ok=True)
            crash_path.write_text(
                "线程：{}\n版本：{}\n时间：{}\n\n{}".format(
                    thread_name,
                    MONITOR_VERSION,
                    datetime.now().isoformat(timespec="seconds"),
                    report,
                ),
                encoding="utf-8",
            )
        except OSError:
            crash_path = None

        detail = "线程：{}\n{}".format(thread_name, report)
        if crash_path is not None:
            detail = "崩溃日志：{}\n\n{}".format(crash_path, detail)
        LOGGER.critical("Windows 托盘发生未捕获异常\n%s", report)

        # 多个后台线程同时失败时只显示一个模态窗口，避免 Tk 根窗口互相争用。
        if not self.crash_dialog_lock.acquire(False):
            return
        try:
            self._configure_tk_runtime()
            self._show_copyable_error_dialog(
                None,
                "OmniWatch USB监控屏崩溃",
                "应用发生未处理异常，请复制下方崩溃信息并反馈。",
                detail=detail,
            )
        except Exception:
            LOGGER.exception("显示托盘崩溃弹框失败")
        finally:
            self.crash_dialog_lock.release()

    def _install_thread_crash_handler(self):
        """安装后台线程未捕获异常处理器，并返回原处理器。"""
        original_hook = threading.excepthook

        def handle_thread_crash(arguments):
            """把后台线程异常转交给统一崩溃日志与弹框流程。"""
            self._report_unhandled_crash(
                arguments.exc_type,
                arguments.exc_value,
                arguments.exc_traceback,
                getattr(arguments.thread, "name", "后台线程"),
            )

        threading.excepthook = handle_thread_crash
        return original_hook

    @staticmethod
    def _should_use_copyable_custom_style_error(title):
        """判断自定义屏幕弹框中的错误是否需要可复制错误详情。"""
        title_text = str(title or "")
        keywords = ("上传", "样式", "自定义屏幕", "自定义样式")
        return any(keyword in title_text for keyword in keywords)

    def _run_settings_window(self):
        """使用原生控件绘制接近 Element Plus 的分组配置对话框。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        self.settings_window = root
        root.title("OmniWatch 配置")
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
            "port": tk.StringVar(master=root, value=self.settings["port"]),
            "ping_target": tk.StringVar(master=root, value=self.settings["ping_target"]),
            "interval": tk.StringVar(master=root, value=self.settings["interval"]),
            "reconnect_interval": tk.StringVar(master=root, value=self.settings["reconnect_interval"]),
            "serial_probe_interval": tk.StringVar(master=root, value=self.settings["serial_probe_interval"]),
            "screen_rotation": tk.StringVar(master=root, value=str(self.settings["screen_rotation"])),
            "lcd_brightness": tk.IntVar(master=root, value=self.settings["lcd_brightness"]),
            "network_unit": tk.StringVar(master=root, value=self.settings["network_unit"]),
            "lcd_style": tk.StringVar(
                master=root,
                value=style_label(self.settings["lcd_style"], self.settings)
            ),
            "qbittorrent_enabled": tk.BooleanVar(master=root, value=False),
            "qbittorrent_address": tk.StringVar(master=root, value=self.settings["qbittorrent_address"]),
            "qbittorrent_username": tk.StringVar(master=root, value=self.settings["qbittorrent_username"]),
            "qbittorrent_password": tk.StringVar(master=root, value=self.settings["qbittorrent_password"]),
            "qbittorrent_interval": tk.StringVar(master=root, value=self.settings["qbittorrent_interval"]),
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
                messagebox.showerror("应用失败", "OmniWatch 未运行，显示设置暂未应用。", parent=root)
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
                    "串口已保存：{}；OmniWatch 已重启".format(
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

    def _show_custom_data(self, icon=None, item=None):
        """打开自定义数据管理弹框。"""
        del icon, item
        threading.Thread(target=self._run_custom_data_dialog_guarded, name="自定义数据窗口", daemon=True).start()

    def _run_custom_data_dialog_guarded(self):
        """运行自定义数据窗口，并将 Tk 初始化错误降级为日志和托盘通知。"""
        try:
            self._run_custom_data_dialog()
        except Exception as error:
            LOGGER.exception("打开自定义数据窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开自定义数据窗口，请查看日志", APPLICATION_NAME)

    def _run_custom_data_dialog(self):
        """显示自定义数据脚本列表并处理加载、测试、删除和查看。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        manager = custom_data.get_manager()
        root = tk.Tk()
        root.title("自定义数据")
        root.geometry("860x560")
        root.minsize(760, 460)
        self._set_tk_window_icon(root)

        status = tk.StringVar(master=root, value="目录：{}".format(manager.custom_directory))
        tk.Label(root, textvariable=status, anchor="w", padx=10, pady=8).pack(fill=tk.X)

        columns = ("file", "key", "interval", "status")
        table = ttk.Treeview(root, columns=columns, show="headings", height=10)
        table.heading("file", text="文件")
        table.heading("key", text="JSON Key")
        table.heading("interval", text="间隔(秒)")
        table.heading("status", text="状态")
        table.column("file", width=280, anchor="w")
        table.column("key", width=140, anchor="w")
        table.column("interval", width=90, anchor="center")
        table.column("status", width=220, anchor="w")
        table.pack(fill=tk.BOTH, expand=True, padx=10)

        button_frame = tk.Frame(root, padx=10, pady=8)
        button_frame.pack(fill=tk.X)
        output = scrolledtext.ScrolledText(root, height=9, wrap=tk.WORD)
        output.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        path_by_item = {}

        def write_output(content):
            """把操作结果写入底部文本域。"""
            output.configure(state=tk.NORMAL)
            output.delete("1.0", tk.END)
            output.insert(tk.END, content)
            output.configure(state=tk.NORMAL)

        def selected_path():
            """返回当前选中的脚本路径，未选中时提示用户。"""
            selection = table.selection()
            if not selection:
                messagebox.showinfo("自定义数据", "请先选择一个脚本", parent=root)
                return None
            return path_by_item.get(selection[0])

        def refresh():
            """刷新脚本列表和加载错误。"""
            path_by_item.clear()
            for item in table.get_children():
                table.delete(item)
            items, errors = manager.list_items()
            for state in items:
                definition = state.definition
                status_text = "正常" if not state.error else "执行错误"
                item = table.insert("", tk.END, values=(
                    definition.path.name,
                    definition.key,
                    "{:g}".format(definition.interval),
                    status_text,
                ))
                path_by_item[item] = definition.path
            for script_path, error in errors.items():
                item = table.insert("", tk.END, values=(Path(script_path).name, "加载失败", "-", error))
                path_by_item[item] = Path(script_path)
            status.set("目录：{}    已加载：{}，错误：{}".format(manager.custom_directory, len(items), len(errors)))

        def load_script():
            """选择 py 文件并加载到 customData 目录。"""
            script_path = filedialog.askopenfilename(
                parent=root,
                title="加载自定义数据脚本",
                filetypes=(("Python 脚本", "*.py"), ("所有文件", "*.*")),
            )
            if not script_path:
                return
            try:
                definition = manager.import_script(script_path)
                write_output("加载成功：{}\nkey={}\ninterval={:g}s".format(
                    definition.path.name,
                    definition.key,
                    definition.interval,
                ))
                refresh()
            except Exception as error:
                write_output("加载失败：{}".format(error))

        def test_script():
            """测试执行当前选中脚本并展示 JSON 或异常详情。"""
            script_path = selected_path()
            if script_path is not None:
                write_output(manager.test_script(script_path))

        def delete_script():
            """删除当前选中的 customData 脚本。"""
            script_path = selected_path()
            if script_path is None:
                return
            if not messagebox.askyesno("删除自定义数据", "确认删除 {}？".format(Path(script_path).name), parent=root):
                return
            try:
                manager.delete_script(script_path)
                write_output("删除成功")
                refresh()
            except Exception as error:
                write_output("删除失败：{}".format(error))

        def view_script():
            """在只读窗口中查看当前选中脚本源码。"""
            script_path = selected_path()
            if script_path is None:
                return
            window = tk.Toplevel(root)
            window.title("查看 - {}".format(Path(script_path).name))
            window.geometry("760x520")
            self._set_tk_window_icon(window)
            text_box = scrolledtext.ScrolledText(window, wrap=tk.NONE)
            text_box.pack(fill=tk.BOTH, expand=True)
            try:
                text_box.insert(tk.END, Path(script_path).read_text(encoding="utf-8"))
            except Exception as error:
                text_box.insert(tk.END, "读取失败：{}".format(error))
            text_box.configure(state=tk.DISABLED)

        ttk.Button(button_frame, text="加载 py 文件", command=load_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="测试", command=test_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="删除", command=delete_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="查看", command=view_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="刷新", command=refresh).pack(side=tk.LEFT)
        refresh()
        root.mainloop()

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

    def _show_custom_style(self, icon=None, item=None):
        """打开自定义屏幕弹框，并通过后台进程向 Pico 获取最新清单。"""
        del icon, item
        import tkinter.messagebox as messagebox

        from .customStyle.dialog import show_custom_style_dialog

        original_showerror = messagebox.showerror

        def showerror_with_copy(title=None, message=None, **options):
            """在自定义屏幕窗口内把上传失败弹框替换为可复制版本。"""
            if self._should_use_copyable_custom_style_error(title):
                parent = options.get("parent") or self.settings_window
                detail = options.get("detail")
                if detail is None and isinstance(message, BaseException):
                    detail = repr(message)
                self._show_copyable_error_dialog(
                    parent,
                    title or "上传样式失败",
                    message or "未知错误",
                    detail=detail,
                )
                return "ok"
            return original_showerror(title, message, **options)

        messagebox.showerror = showerror_with_copy
        try:
            show_custom_style_dialog(self)
        finally:
            if messagebox.showerror is showerror_with_copy:
                messagebox.showerror = original_showerror

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
