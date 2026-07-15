"""Windows 监控配置窗口。"""

import queue
import threading

from qbittorrent_monitor import QbittorrentApiClient

from ..constants import APPLICATION_NAME
from ..settings import (
    COLLECTION_TASK_ZH_NAMES,
    DEFAULT_COLLECTION_TASK_INTERVALS,
    normalize_collection_task_intervals,
    style_label,
    style_names,
)


class SettingsWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

    def _show_settings(self, icon=None, item=None):
        """打开唯一的配置窗口，重复调用时恢复现有窗口。"""
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
        """运行配置窗口，并在退出后清理窗口状态。"""
        try:
            self._run_settings_window()
        finally:
            self.settings_window = None
            with self.settings_window_lock:
                self.settings_window_open = False

    def _run_settings_window(self):
        """使用原生控件绘制接近 Element Plus 的分组配置对话框。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.withdraw()
        self.settings_window = root
        root.title("OmniWatch 配置")
        self._set_tk_window_icon(root)
        root.geometry("680x700")
        root.minsize(620, 620)
        root.configure(bg="#f5f7fa")
        root.option_add("*Font", ("Microsoft YaHei UI", 10))

        def restore_when_requested():
            """处理托盘重复点击产生的窗口恢复请求。"""
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
            """根据内容尺寸更新配置画布的滚动范围。"""
            del event
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_scroll_body(event):
            """让配置内容宽度随画布可用宽度变化。"""
            canvas.itemconfigure(body_window, width=event.width)

        def scroll_with_mouse(event):
            """响应鼠标滚轮并滚动配置内容。"""
            if event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        body.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_scroll_body)
        root.bind("<MouseWheel>", scroll_with_mouse)

        ttk.Label(body, text="配置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="显示设置可即时应用，其他配置保存后会重启监控服务", style="Hint.TLabel").pack(anchor="w", pady=(2, 18))

        variables = {
            "port": tk.StringVar(master=root, value=self.settings["port"]),
            "websocket_client_name": tk.StringVar(
                master=root,
                value=self.settings.get("websocket_client_name", "Monitor"),
            ),
            "ping_target": tk.StringVar(master=root, value=self.settings["ping_target"]),
            "interval": tk.StringVar(master=root, value=self.settings["interval"]),
            "adaptive_transmit": tk.BooleanVar(master=root, value=bool(self.settings.get("adaptive_transmit", True))),
            "collection_task_logs": tk.BooleanVar(master=root, value=bool(self.settings.get("collection_task_logs", True))),
            "reconnect_interval": tk.StringVar(master=root, value=self.settings["reconnect_interval"]),
            "serial_probe_interval": tk.StringVar(master=root, value=self.settings["serial_probe_interval"]),
            "screen_rotation": tk.StringVar(master=root, value=str(self.settings["screen_rotation"])),
            "lcd_brightness": tk.IntVar(master=root, value=self.settings["lcd_brightness"]),
            "network_unit": tk.StringVar(master=root, value=self.settings["network_unit"]),
            "lcd_style": tk.StringVar(
                master=root,
                value=style_label(self.settings["lcd_style"], self.settings)
            ),
            "idle_style": tk.StringVar(
                master=root,
                value=style_label(self.settings["idle_style"], self.settings),
            ),
            "idle_timeout": tk.StringVar(
                master=root,
                value=str(self.settings.get("idle_timeout", 30)),
            ),
            "qbittorrent_enabled": tk.BooleanVar(master=root, value=False),
            "qbittorrent_address": tk.StringVar(master=root, value=self.settings["qbittorrent_address"]),
            "qbittorrent_username": tk.StringVar(master=root, value=self.settings["qbittorrent_username"]),
            "qbittorrent_password": tk.StringVar(master=root, value=self.settings["qbittorrent_password"]),
            "qbittorrent_interval": tk.StringVar(master=root, value=self.settings["qbittorrent_interval"]),
        }
        collection_task_variables = {
            name: tk.StringVar(
                master=root,
                value="{:g}".format(
                    normalize_collection_task_intervals(
                        self.settings.get("collection_task_intervals")
                    )[name]
                ),
            )
            for name in DEFAULT_COLLECTION_TASK_INTERVALS
        }

        def card(title):
            """创建带标题的配置分组卡片。"""
            frame = ttk.LabelFrame(body, text=title, style="Card.TLabelframe", padding=16)
            frame.pack(fill="x", pady=(0, 14))
            frame.columnconfigure(1, weight=1)
            return frame

        def field(parent, row, label, widget):
            """向配置分组添加一行标签和输入控件。"""
            ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)
            widget.grid(row=row, column=1, sticky="ew", pady=6)

        display = card("显示设置")
        styles = [style_label(name, self.settings) for name in style_names(self.settings, idle=False)]
        idle_styles = [style_label(name, self.settings) for name in style_names(self.settings, idle=True)]
        field(display, 0, "界面样式", ttk.Combobox(display, textvariable=variables["lcd_style"], values=styles, state="readonly"))
        field(display, 1, "待机样式", ttk.Combobox(display, textvariable=variables["idle_style"], values=idle_styles, state="readonly"))
        field(display, 2, "空闲进入待机（秒）", ttk.Entry(display, textvariable=variables["idle_timeout"]))
        field(display, 3, "屏幕旋转", ttk.Combobox(display, textvariable=variables["screen_rotation"], values=("0", "180"), state="readonly"))
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
        field(display, 4, "背光亮度（1-100%）", brightness_control)
        field(display, 5, "网络速率单位", ttk.Combobox(display, textvariable=variables["network_unit"], values=("MB", "Mbps"), state="readonly"))

        def save_display_settings():
            """保存显示设置并通知运行中的 Monitor 在下一帧应用。"""
            try:
                selected_style = next(
                    name for name in style_names(self.settings, idle=False)
                    if style_label(name, self.settings) == variables["lcd_style"].get()
                )
                selected_idle_style = next(
                    name for name in style_names(self.settings, idle=True)
                    if style_label(name, self.settings) == variables["idle_style"].get()
                )
                brightness = int(variables["lcd_brightness"].get())
                idle_timeout = int(variables["idle_timeout"].get())
                if not 1 <= brightness <= 100:
                    raise ValueError
                if idle_timeout <= 0:
                    raise ValueError
            except (ValueError, StopIteration):
                messagebox.showerror("配置错误", "背光亮度必须为 1 至 100，待机秒数必须大于 0。", parent=root)
                return
            self.settings.update({
                "lcd_style": selected_style,
                "idle_style": selected_idle_style,
                "idle_timeout": idle_timeout,
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
        ).grid(row=6, column=1, sticky="e", pady=(10, 0))

        monitor = card("监控连接")
        port_control = ttk.Frame(monitor)
        port_control.columnconfigure(0, weight=1)
        ttk.Entry(port_control, textvariable=variables["port"]).grid(row=0, column=0, sticky="ew")

        def save_port():
            """保存串口设置并重启后台监控进程。"""
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
        adaptive_control = ttk.Checkbutton(
            monitor,
            text="启用间隔自适应（根据 ACK 在 300ms 以上升降，拥塞时合并最新快照）",
            variable=variables["adaptive_transmit"],
        )
        field(monitor, 3, "发送背压", adaptive_control)
        field(monitor, 4, "重连间隔（秒）", ttk.Entry(monitor, textvariable=variables["reconnect_interval"]))
        field(monitor, 5, "串口探测 PING 间隔（秒）", ttk.Entry(monitor, textvariable=variables["serial_probe_interval"]))
        field(monitor, 6, "WebSocket 客户端名称", ttk.Entry(monitor, textvariable=variables["websocket_client_name"]))

        collection_tasks = card("系统采集任务")
        collection_task_logs_control = ttk.Checkbutton(
            collection_tasks,
            text="输出采集任务提交、开始、完成及线程池状态日志（错误和告警始终保留）",
            variable=variables["collection_task_logs"],
        )
        field(collection_tasks, 0, "任务日志", collection_task_logs_control)
        for row, (task_name, variable) in enumerate(collection_task_variables.items(), start=1):
            default_interval = DEFAULT_COLLECTION_TASK_INTERVALS[task_name]
            task_label = COLLECTION_TASK_ZH_NAMES.get(task_name, task_name)
            field(
                collection_tasks,
                row,
                "{}（{}，默认 {:g} 秒）".format(task_label, task_name, default_interval),
                ttk.Entry(collection_tasks, textvariable=variable),
            )

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
            """读取当前表单中的 qBittorrent 登录信息。"""
            return (
                variables["qbittorrent_address"].get().strip(),
                variables["qbittorrent_username"].get().strip(),
                variables["qbittorrent_password"].get(),
            )

        def invalidate_qbittorrent_verification(*unused):
            """在登录信息变化后使已有验证结果失效。"""
            del unused
            verified_qbittorrent_credentials[0] = None
            variables["qbittorrent_enabled"].set(False)
            enable_qbittorrent.configure(state="disabled")

        for name in ("qbittorrent_address", "qbittorrent_username", "qbittorrent_password"):
            variables[name].trace_add("write", invalidate_qbittorrent_verification)

        def verify_qbittorrent():
            """在后台线程中验证 qBittorrent 登录信息。"""
            credentials = current_qbittorrent_credentials()
            if not all(credentials):
                messagebox.showerror("验证失败", "请先填写 Web UI 地址、用户名和密码。", parent=root)
                return
            verification_button.configure(state="disabled", text="正在验证...")
            enable_qbittorrent.configure(state="disabled")
            variables["qbittorrent_enabled"].set(False)

            def run_verification():
                """执行 qBittorrent 登录并提交验证结果。"""
                try:
                    QbittorrentApiClient(*credentials).login()
                    verification_results.put((credentials, None))
                except Exception as error:  # 网络和认证错误均反馈到配置页。
                    verification_results.put((credentials, str(error)))

            threading.Thread(target=run_verification, name="qBittorrent 账号验证", daemon=True).start()

        verification_button.configure(command=verify_qbittorrent)

        def consume_verification_result():
            """消费登录验证结果并更新配置控件状态。"""
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
            """校验并保存完整配置，然后重启后台监控。"""
            try:
                selected_style = next(name for name in style_names(self.settings, idle=False) if style_label(name, self.settings) == variables["lcd_style"].get())
                selected_idle_style = next(name for name in style_names(self.settings, idle=True) if style_label(name, self.settings) == variables["idle_style"].get())
                collection_task_intervals = {}
                for name, variable in collection_task_variables.items():
                    interval = float(variable.get())
                    if interval <= 0:
                        raise ValueError
                    collection_task_intervals[name] = interval
                collection_task_intervals = normalize_collection_task_intervals(collection_task_intervals)
                updated = dict(self.settings)
                updated.update({
                    "port": variables["port"].get().strip(),
                    "websocket_client_name": variables["websocket_client_name"].get().strip(),
                    "ping_target": variables["ping_target"].get().strip(),
                    "interval": float(variables["interval"].get()),
                    "adaptive_transmit": bool(variables["adaptive_transmit"].get()),
                    "reconnect_interval": float(variables["reconnect_interval"].get()),
                    "serial_probe_interval": float(variables["serial_probe_interval"].get()),
                    "collection_task_intervals": collection_task_intervals,
                    "collection_task_logs": bool(variables["collection_task_logs"].get()),
                    "screen_rotation": int(variables["screen_rotation"].get()),
                    "lcd_brightness": int(variables["lcd_brightness"].get()),
                    "network_unit": variables["network_unit"].get(),
                    "lcd_style": selected_style,
                    "idle_style": selected_idle_style,
                    "idle_timeout": int(variables["idle_timeout"].get()),
                    "qbittorrent_enabled": variables["qbittorrent_enabled"].get(),
                    "qbittorrent_address": variables["qbittorrent_address"].get().strip(),
                    "qbittorrent_username": variables["qbittorrent_username"].get().strip(),
                    "qbittorrent_password": variables["qbittorrent_password"].get(),
                    "qbittorrent_interval": float(variables["qbittorrent_interval"].get()),
                })
                if (not updated["ping_target"]
                        or not updated["websocket_client_name"]
                        or updated["interval"] < 0.3
                        or min(updated["reconnect_interval"], updated["serial_probe_interval"], updated["qbittorrent_interval"]) <= 0
                        or min(updated["collection_task_intervals"].values()) <= 0
                        or updated["idle_timeout"] <= 0
                        or not 1 <= updated["lcd_brightness"] <= 100):
                    raise ValueError
                if updated["qbittorrent_enabled"] and not all((updated["qbittorrent_address"], updated["qbittorrent_username"], updated["qbittorrent_password"])):
                    messagebox.showerror("配置错误", "启用 qBittorrent 后，请填写地址、用户名和密码。", parent=root)
                    return
                if updated["qbittorrent_enabled"] and current_qbittorrent_credentials() != verified_qbittorrent_credentials[0]:
                    messagebox.showerror("配置错误", "请先验证 qBittorrent 账号密码，验证成功后才能启用指标采集。", parent=root)
                    return
            except (ValueError, StopIteration):
                messagebox.showerror(
                    "配置错误",
                    "请检查设备名称、地址和时间间隔；JSON 采集间隔不得低于 0.3 秒。",
                    parent=root,
                )
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
            """关闭配置窗口。"""
            root.destroy()
        root.protocol("WM_DELETE_WINDOW", closed)
        self._show_centered_tk_window(root)
        root.mainloop()
