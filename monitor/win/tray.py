#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.

"""Windows 托盘、配置窗口、开机自启和后台进程管理。"""

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import winreg
from datetime import datetime
from pathlib import Path

from qbittorrent_monitor import QbittorrentApiClient

from .settings import (
    DEFAULT_SETTINGS,
    TraySettingsStore,
    apply_worker_arguments,
    settings_from_arguments,
    style_label,
    style_names,
)

APPLICATION_NAME = "Pico 系统监控"
AUTOSTART_NAME = "PicoHardwareMonitor"
MONITOR_DIRECTORY = Path(__file__).resolve().parent.parent
LOG_EXPORT_SIZE = 1024 * 1024


class WindowsTrayApplication:
    """管理 Windows 托盘图标、配置界面和无窗口监控工作进程。"""

    def __init__(self, worker_arguments):
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
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PicoHardwareMonitor")
        return ctypes.windll.kernel32.GetLastError() != 183

    def _worker_command(self):
        arguments = apply_worker_arguments(self.worker_arguments, self.settings)
        if getattr(sys, "frozen", False):
            return [sys.executable, *arguments]
        return [sys.executable, str(MONITOR_DIRECTORY / "pico_monitor.py"), *arguments]

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
        process = self.worker_process
        with self.log_path.open("a", encoding="utf-8", newline="") as log_file:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
                if "STYLE_CATALOG_UPDATED" in line:
                    self.settings = self.settings_store.load()
                    if self.icon is not None:
                        self.icon.menu = self._build_menu()
                        self.icon.update_menu()
        return_code = process.wait()
        if not self.stopping.is_set() and process is self.worker_process and self.icon is not None:
            self.icon.notify("后台监控已退出，返回码：{}".format(return_code), APPLICATION_NAME)

    def _show_log(self, icon=None, item=None):
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

    def _run_settings_window_guarded(self):
        try:
            self._run_settings_window()
        finally:
            self.settings_window = None
            with self.settings_window_lock:
                self.settings_window_open = False

    def _run_settings_window(self):
        """使用原生控件绘制接近 Element Plus 的分组配置对话框。"""
        python_root = Path(sys.base_prefix)
        tcl_dir = python_root / "tcl" / "tcl8.6"
        tk_dir = python_root / "tcl" / "tk8.6"

        if (tcl_dir / "init.tcl").exists():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)

        if (tk_dir / "tk.tcl").exists():
            os.environ["TK_LIBRARY"] = str(tk_dir)

        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        self.settings_window = root
        root.title("Pico Monitor 配置")
        icon_directory = Path(getattr(sys, "_MEIPASS", MONITOR_DIRECTORY))
        settings_icon = tk.PhotoImage(file=icon_directory / "icon" / "icon.png")
        root.iconphoto(True, settings_icon)
        root.settings_icon = settings_icon
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
                        or min(updated["interval"], updated["reconnect_interval"], updated["qbittorrent_interval"]) <= 0
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

    def _build_menu(self):
        import pystray

        style_menu = pystray.Menu(*(
            pystray.MenuItem(style_label(name, self.settings), self._select_style(name), checked=self._style_checked(name), radio=True)
            for name in style_names(self.settings)
        ))
        return pystray.Menu(
            pystray.MenuItem("配置...", self._show_settings, default=True),
            pystray.MenuItem("界面样式", style_menu),
            pystray.MenuItem("屏幕旋转", pystray.Menu(
                pystray.MenuItem("0°", self._set_rotation(0), checked=lambda item: self.settings["screen_rotation"] == 0, radio=True),
                pystray.MenuItem("180°", self._set_rotation(180), checked=lambda item: self.settings["screen_rotation"] == 180, radio=True),
            )),
            pystray.MenuItem("打开日志", self._show_log),
            pystray.MenuItem("日志导出", self._export_log),
            pystray.MenuItem("Dev 模式", self._toggle_dev_mode, checked=self._is_dev_mode),
            pystray.MenuItem("开机自动启动", self._toggle_autostart, checked=self._is_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit),
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
        import pystray

        if not self._acquire_single_instance():
            return 0
        self._start_worker()
        self.icon = pystray.Icon("pico-monitor", self._create_image(), APPLICATION_NAME, self._build_menu())
        self.icon.run()
        return 0
