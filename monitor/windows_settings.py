"""Windows 托盘的持久化配置和轻量图形设置窗口。"""

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


LCD_STYLES = (
    "default", "disk", "diskv2", "diskv3", "diskv4", "horizontal_disk",
    "horizontal_diskv2", "horizontal_disk4x", "horizontal_disk4x_qb",
    "horizontal_disk6x", "simple",
)

DEFAULT_SETTINGS = {
    "port": "",
    "ping_target": "www.baidu.com",
    "interval": 0.5,
    "reconnect_interval": 3.0,
    "screen_rotation": 0,
    "network_unit": "MB",
    "lcd_style": "horizontal_disk4x_qb",
    "qbittorrent_enabled": False,
    "qbittorrent_address": "",
    "qbittorrent_username": "",
    "qbittorrent_password": "",
    "qbittorrent_interval": 2.0,
}


class SettingsStore:
    """读写当前用户配置，并生成 Monitor 命令行参数。"""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                settings.update({key: value[key] for key in settings.keys() & value.keys()})
        except (OSError, ValueError, TypeError):
            pass
        return settings

    def save(self, settings):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def worker_arguments(settings):
        arguments = [
            "--port", str(settings["port"]).strip(),
            "--ping-target", str(settings["ping_target"]),
            "--interval", str(settings["interval"]),
            "--reconnect-interval", str(settings["reconnect_interval"]),
            "--screen-rotation", str(settings["screen_rotation"]),
            "--network-unit", str(settings["network_unit"]),
            "--lcd-style", str(settings["lcd_style"]),
            "--qbittorrent-interval", str(settings["qbittorrent_interval"]),
            "--qbittorrent-address", str(settings["qbittorrent_address"]).strip(),
            "--qbittorrent-username", str(settings["qbittorrent_username"]).strip(),
            "--qbittorrent-password", str(settings["qbittorrent_password"]).strip(),
        ]
        arguments.append("--qbittorrent-enabled" if settings["qbittorrent_enabled"] else "--no-qbittorrent")
        return arguments


class SettingsWindow:
    """接近 Element UI 视觉的单实例设置窗口。"""

    BLUE = "#409eff"
    TEXT = "#303133"
    MUTED = "#909399"
    BORDER = "#dcdfe6"
    BACKGROUND = "#f5f7fa"

    def __init__(self, store, on_saved):
        self.store = store
        self.on_saved = on_saved
        self.root = None
        self.variables = {}

    def show(self):
        if self.root is not None and self.root.winfo_exists():
            self.root.after(0, self._focus)
            return
        self._build()
        self.root.mainloop()

    def _focus(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _build(self):
        root = tk.Tk()
        self.root = root
        root.title("Pico Monitor · 设置")
        root.geometry("620x760")
        root.minsize(580, 700)
        root.configure(bg=self.BACKGROUND)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()

        header = tk.Frame(root, bg="white", padx=28, pady=20)
        header.pack(fill="x")
        tk.Label(header, text="Monitor 设置", font=("Microsoft YaHei UI", 16, "bold"), fg=self.TEXT, bg="white").pack(anchor="w")
        tk.Label(header, text="保存后后台服务将自动重启并应用新配置", font=("Microsoft YaHei UI", 9), fg=self.MUTED, bg="white").pack(anchor="w", pady=(6, 0))

        body = ttk.Frame(root, style="Card.TFrame", padding=(28, 22))
        body.pack(fill="both", expand=True, padx=20, pady=18)
        settings = self.store.load()
        self._section(body, "连接与采集")
        self._entry(body, "串口", "port", settings, "留空自动发现，例如 COM3")
        self._entry(body, "Ping 目标", "ping_target", settings)
        timing = ttk.Frame(body, style="Card.TFrame")
        timing.pack(fill="x", pady=(0, 14))
        self._entry(timing, "采集间隔（秒）", "interval", settings, column=0)
        self._entry(timing, "重连间隔（秒）", "reconnect_interval", settings, column=1)

        self._section(body, "屏幕显示")
        display = ttk.Frame(body, style="Card.TFrame")
        display.pack(fill="x", pady=(0, 14))
        self._combo(display, "旋转", "screen_rotation", settings, (0, 180), 0)
        self._combo(display, "网络单位", "network_unit", settings, ("MB", "Mbps"), 1)
        self._combo(body, "LCD 样式", "lcd_style", settings, LCD_STYLES)

        self._section(body, "qBittorrent")
        enabled = tk.BooleanVar(value=bool(settings["qbittorrent_enabled"]))
        self.variables["qbittorrent_enabled"] = enabled
        ttk.Checkbutton(body, text="启用 qBittorrent 指标采集", variable=enabled, style="Switch.TCheckbutton").pack(anchor="w", pady=(0, 13))
        self._entry(body, "Web UI 地址", "qbittorrent_address", settings, "例如 http://127.0.0.1:8080")
        credentials = ttk.Frame(body, style="Card.TFrame")
        credentials.pack(fill="x")
        self._entry(credentials, "用户名", "qbittorrent_username", settings, column=0)
        self._entry(credentials, "密码", "qbittorrent_password", settings, column=1, password=True)
        self._entry(body, "采集间隔（秒）", "qbittorrent_interval", settings)

        footer = tk.Frame(root, bg=self.BACKGROUND, padx=20, pady=(0, 18))
        footer.pack(fill="x")
        ttk.Button(footer, text="取消", command=self._close, style="Plain.TButton").pack(side="right")
        ttk.Button(footer, text="保存并应用", command=self._save, style="Primary.TButton").pack(side="right", padx=(0, 10))

    def _configure_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="white", foreground=self.TEXT, font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", fieldbackground="white", bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER, padding=7)
        style.configure("TCombobox", fieldbackground="white", bordercolor=self.BORDER, padding=6)
        style.configure("Primary.TButton", background=self.BLUE, foreground="white", borderwidth=0, padding=(18, 9), font=("Microsoft YaHei UI", 9))
        style.map("Primary.TButton", background=[("active", "#66b1ff")])
        style.configure("Plain.TButton", background="white", foreground=self.TEXT, bordercolor=self.BORDER, padding=(18, 9))
        style.configure("Switch.TCheckbutton", background="white", foreground=self.TEXT)

    @staticmethod
    def _section(parent, text):
        ttk.Label(parent, text=text, font=("Microsoft YaHei UI", 10, "bold"), foreground="#606266").pack(anchor="w", pady=(2, 12))

    def _entry(self, parent, label, key, settings, placeholder="", column=None, password=False):
        frame = ttk.Frame(parent, style="Card.TFrame")
        if column is None:
            frame.pack(fill="x", pady=(0, 12))
        else:
            frame.grid(row=0, column=column, sticky="ew", padx=((0, 8) if column == 0 else (8, 0)))
            parent.columnconfigure(column, weight=1)
        ttk.Label(frame, text=label).pack(anchor="w", pady=(0, 6))
        variable = tk.StringVar(value=str(settings[key]))
        self.variables[key] = variable
        ttk.Entry(frame, textvariable=variable, show="•" if password else "").pack(fill="x")
        if placeholder:
            ttk.Label(frame, text=placeholder, foreground=self.MUTED, font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(4, 0))

    def _combo(self, parent, label, key, settings, values, column=None):
        frame = ttk.Frame(parent, style="Card.TFrame")
        if column is None:
            frame.pack(fill="x", pady=(0, 14))
        else:
            frame.grid(row=0, column=column, sticky="ew", padx=((0, 8) if column == 0 else (8, 0)))
            parent.columnconfigure(column, weight=1)
        ttk.Label(frame, text=label).pack(anchor="w", pady=(0, 6))
        variable = tk.StringVar(value=str(settings[key]))
        self.variables[key] = variable
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly").pack(fill="x")

    def _save(self):
        settings = {key: variable.get() for key, variable in self.variables.items()}
        try:
            settings["interval"] = float(settings["interval"])
            settings["reconnect_interval"] = float(settings["reconnect_interval"])
            settings["qbittorrent_interval"] = float(settings["qbittorrent_interval"])
            settings["screen_rotation"] = int(settings["screen_rotation"])
            settings["qbittorrent_enabled"] = bool(settings["qbittorrent_enabled"])
            if min(settings["interval"], settings["reconnect_interval"], settings["qbittorrent_interval"]) <= 0:
                raise ValueError
            if settings["qbittorrent_enabled"] and not all(str(settings[key]).strip() for key in ("qbittorrent_address", "qbittorrent_username", "qbittorrent_password")):
                messagebox.showwarning("配置不完整", "启用 qBittorrent 后，请填写地址、用户名和密码。", parent=self.root)
                return
        except (TypeError, ValueError):
            messagebox.showwarning("格式有误", "三个间隔必须是大于 0 的数字。", parent=self.root)
            return
        self.store.save(settings)
        self.on_saved(settings)
        self._close()

    def _close(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None
