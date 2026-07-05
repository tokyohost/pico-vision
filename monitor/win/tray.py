#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.

"""Windows 托盘、配置窗口、开机自启和后台进程管理。"""

import ctypes
import os
import subprocess
import sys
import threading
import winreg
from pathlib import Path

from .settings import (
    DEFAULT_SETTINGS,
    STYLE_NAMES,
    TraySettingsStore,
    apply_worker_arguments,
    settings_from_arguments,
    style_label,
)

APPLICATION_NAME = "Pico 系统监控"
AUTOSTART_NAME = "PicoHardwareMonitor"
MONITOR_DIRECTORY = Path(__file__).resolve().parent.parent


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
        data_directory = Path(os.getenv("LOCALAPPDATA", Path.home())) / "PicoMonitor"
        data_directory.mkdir(parents=True, exist_ok=True)
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

    def _collect_output(self):
        process = self.worker_process
        with self.log_path.open("a", encoding="utf-8", newline="") as log_file:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
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

    def _select_style(self, style):
        def select(icon, item):
            del item
            self.settings["lcd_style"] = style
            self.settings_store.save(self.settings)
            self._restart_worker()
            icon.update_menu()
            icon.notify("已切换为{}".format(STYLE_NAMES[style]), APPLICATION_NAME)
        return select

    def _style_checked(self, style):
        return lambda item: self.settings["lcd_style"] == style

    def _show_settings(self, icon=None, item=None):
        del item
        with self.settings_window_lock:
            if self.settings_window_open:
                if icon is not None:
                    icon.notify("配置窗口已经打开", APPLICATION_NAME)
                return
            # 在创建线程前占位，避免连续点击同时创建多个 Tk 窗口。
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
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        self.settings_window = root
        root.title("Pico Monitor 配置")
        root.geometry("680x700")
        root.minsize(620, 620)
        root.configure(bg="#f5f7fa")
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style(root)
        style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"), foreground="#303133", background="#f5f7fa")
        style.configure("Hint.TLabel", foreground="#909399", background="#f5f7fa")
        style.configure("Card.TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", font=("Microsoft YaHei UI", 11, "bold"), foreground="#303133", background="#ffffff")
        style.configure("Card.TLabel", foreground="#606266", background="#ffffff")
        style.configure("Primary.TButton", foreground="#ffffff", background="#409eff", padding=(18, 8))

        body = ttk.Frame(root, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="配置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="保存后监控服务会自动重启并应用新设置", style="Hint.TLabel").pack(anchor="w", pady=(2, 18))

        variables = {
            "port": tk.StringVar(value=self.settings["port"]),
            "ping_target": tk.StringVar(value=self.settings["ping_target"]),
            "interval": tk.StringVar(value=self.settings["interval"]),
            "reconnect_interval": tk.StringVar(value=self.settings["reconnect_interval"]),
            "screen_rotation": tk.StringVar(value=str(self.settings["screen_rotation"])),
            "network_unit": tk.StringVar(value=self.settings["network_unit"]),
            "lcd_style": tk.StringVar(value=style_label(self.settings["lcd_style"])),
            "qbittorrent_enabled": tk.BooleanVar(value=self.settings["qbittorrent_enabled"]),
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
        styles = [style_label(name) for name in STYLE_NAMES]
        field(display, 0, "界面样式", ttk.Combobox(display, textvariable=variables["lcd_style"], values=styles, state="readonly"))
        field(display, 1, "屏幕旋转", ttk.Combobox(display, textvariable=variables["screen_rotation"], values=("0", "180"), state="readonly"))
        field(display, 2, "网络速率单位", ttk.Combobox(display, textvariable=variables["network_unit"], values=("MB", "Mbps"), state="readonly"))

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
        ttk.Checkbutton(qb, text="启用 qBittorrent 指标采集", variable=variables["qbittorrent_enabled"]).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        field(qb, 1, "Web UI 地址", ttk.Entry(qb, textvariable=variables["qbittorrent_address"]))
        field(qb, 2, "用户名", ttk.Entry(qb, textvariable=variables["qbittorrent_username"]))
        field(qb, 3, "密码", ttk.Entry(qb, textvariable=variables["qbittorrent_password"], show="●"))
        field(qb, 4, "采集间隔（秒）", ttk.Entry(qb, textvariable=variables["qbittorrent_interval"]))

        def save():
            try:
                selected_style = next(name for name in STYLE_NAMES if style_label(name) == variables["lcd_style"].get())
                updated = {
                    "port": variables["port"].get().strip(),
                    "ping_target": variables["ping_target"].get().strip(),
                    "interval": float(variables["interval"].get()),
                    "reconnect_interval": float(variables["reconnect_interval"].get()),
                    "screen_rotation": int(variables["screen_rotation"].get()),
                    "network_unit": variables["network_unit"].get(),
                    "lcd_style": selected_style,
                    "qbittorrent_enabled": variables["qbittorrent_enabled"].get(),
                    "qbittorrent_address": variables["qbittorrent_address"].get().strip(),
                    "qbittorrent_username": variables["qbittorrent_username"].get().strip(),
                    "qbittorrent_password": variables["qbittorrent_password"].get(),
                    "qbittorrent_interval": float(variables["qbittorrent_interval"].get()),
                }
                if not updated["ping_target"] or min(updated["interval"], updated["reconnect_interval"], updated["qbittorrent_interval"]) <= 0:
                    raise ValueError
                if updated["qbittorrent_enabled"] and not all((updated["qbittorrent_address"], updated["qbittorrent_username"], updated["qbittorrent_password"])):
                    messagebox.showerror("配置错误", "启用 qBittorrent 后，请填写地址、用户名和密码。", parent=root)
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

        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=root.destroy).pack(side="right")
        ttk.Button(buttons, text="保存配置", command=save, style="Primary.TButton").pack(side="right", padx=(0, 10))

        def closed():
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", closed)
        root.mainloop()

    def _exit(self, icon, item):
        del item
        self.stopping.set()
        if self.worker_process is not None and self.worker_process.poll() is None:
            try:
                self.worker_process.stdin.write("EXIT_REBOOT\n")
                self.worker_process.stdin.flush()
                self.worker_process.wait(timeout=3)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                self.worker_process.terminate()
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
            pystray.MenuItem(style_label(name), self._select_style(name), checked=self._style_checked(name), radio=True)
            for name in STYLE_NAMES
        ))
        return pystray.Menu(
            pystray.MenuItem("配置...", self._show_settings, default=True),
            pystray.MenuItem("界面样式", style_menu),
            pystray.MenuItem("屏幕旋转", pystray.Menu(
                pystray.MenuItem("0°", self._set_rotation(0), checked=lambda item: self.settings["screen_rotation"] == 0, radio=True),
                pystray.MenuItem("180°", self._set_rotation(180), checked=lambda item: self.settings["screen_rotation"] == 180, radio=True),
            )),
            pystray.MenuItem("打开日志", self._show_log),
            pystray.MenuItem("开机自动启动", self._toggle_autostart, checked=self._is_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit),
        )

    def _set_rotation(self, rotation):
        def select(icon, item):
            del item
            self.settings["screen_rotation"] = rotation
            self.settings_store.save(self.settings)
            self._restart_worker()
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
