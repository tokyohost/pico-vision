"""Windows 设备 Wi-Fi 设置窗口。"""

import queue


def merge_wifi_networks(networks, wifi_status):
    """合并扫描结果与设备已保存网络，并标记当前连接状态。"""
    wifi_status = wifi_status if isinstance(wifi_status, dict) else {}
    saved_ssid = wifi_status.get("ssid") or ""
    connected = bool(wifi_status.get("connected"))
    merged = {}
    for network in networks if isinstance(networks, list) else []:
        if not isinstance(network, dict) or not network.get("ssid"):
            continue
        candidate = dict(network)
        candidate["saved"] = candidate["ssid"] == saved_ssid
        candidate["connected"] = connected and candidate["saved"]
        previous = merged.get(candidate["ssid"])
        if previous is None or candidate.get("rssi", -999) > previous.get("rssi", -999):
            merged[candidate["ssid"]] = candidate
    if saved_ssid and saved_ssid not in merged:
        merged[saved_ssid] = {
            "ssid": saved_ssid,
            "rssi": wifi_status.get("rssi"),
            "security": None,
            "saved": True,
            "connected": connected,
        }
    return sorted(
        merged.values(),
        key=lambda item: (
            not item.get("connected"),
            not item.get("saved"),
            -(item.get("rssi") if isinstance(item.get("rssi"), int) else -999),
            item["ssid"].lower(),
        ),
    )


def wifi_state_label(network):
    """返回无线网络的中文连接状态标签。"""
    if network.get("connected"):
        return "已连接"
    if network.get("saved"):
        return "已保存"
    return "可用"


def wifi_security_label(security):
    """把设备安全类型编码转换为适合界面展示的文本。"""
    if security == 0:
        return "开放"
    if security is None:
        return "未知"
    return "需要密钥"


class WifiWindowMixin:
    """为设备管理窗口提供独立的 Wi-Fi 设置页面。"""

    def _show_wifi_settings(self, parent):
        """打开 Wi-Fi 页面并立即加载设备扫描结果。"""
        import tkinter as tk
        from tkinter import messagebox, ttk

        existing = getattr(parent, "_wifi_settings_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        parent._wifi_settings_window = window
        window.withdraw()
        window.title("Wi-Fi 设置")
        window.geometry("680x580")
        window.minsize(560, 400)
        window.transient(parent)
        window.attributes("-topmost", True)
        self._set_tk_window_icon(window)

        status = tk.StringVar(master=window, value="正在加载设备扫描到的 Wi-Fi……")
        ttk.Label(window, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        progress = ttk.Progressbar(window, mode="indeterminate")
        progress.pack(fill=tk.X, padx=16, pady=(0, 10))

        list_frame = ttk.LabelFrame(window, text="设备扫描到的 Wi-Fi", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        columns = ("ssid", "state", "signal", "security")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        tree.heading("ssid", text="Wi-Fi 名称")
        tree.heading("state", text="状态")
        tree.heading("signal", text="信号")
        tree.heading("security", text="安全性")
        tree.column("ssid", width=260, minwidth=160)
        tree.column("state", width=90, anchor=tk.CENTER)
        tree.column("signal", width=90, anchor=tk.CENTER)
        tree.column("security", width=100, anchor=tk.CENTER)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        form = ttk.LabelFrame(window, text="连接 Wi-Fi", padding=10)
        form.pack(fill=tk.X, padx=16, pady=(0, 12))
        ssid = tk.StringVar(master=window)
        password = tk.StringVar(master=window)
        show_password = tk.BooleanVar(master=window, value=False)
        ttk.Label(form, text="Wi-Fi 名称：").grid(row=0, column=0, sticky=tk.W, pady=3)
        ssid_entry = ttk.Entry(form, textvariable=ssid)
        ssid_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=3)
        ttk.Label(form, text="Wi-Fi 密钥：").grid(row=1, column=0, sticky=tk.W, pady=3)
        password_entry = ttk.Entry(form, textvariable=password, show="●")
        password_entry.grid(row=1, column=1, sticky=tk.EW, pady=3)
        form.columnconfigure(1, weight=1)

        def toggle_password_visibility():
            """根据复选框状态显示或隐藏 Wi-Fi 密钥。"""
            password_entry.configure(show="" if show_password.get() else "●")

        ttk.Checkbutton(
            form,
            text="显示密钥",
            variable=show_password,
            command=toggle_password_visibility,
        ).grid(row=1, column=2, padx=(8, 0), pady=3)

        actions = ttk.Frame(window)
        actions.pack(fill=tk.X, padx=16, pady=(0, 16))
        refresh_button = ttk.Button(actions, text="重新扫描")
        refresh_button.pack(side=tk.LEFT)
        connect_button = ttk.Button(actions, text="连接", state=tk.DISABLED)
        connect_button.pack(side=tk.RIGHT)
        forget_button = ttk.Button(actions, text="忘记网络", state=tk.DISABLED)
        forget_button.pack(side=tk.RIGHT, padx=(0, 8))
        operation = {"action": None}
        displayed_networks = {}

        def set_busy(action, message):
            """切换页面忙碌状态并锁定重复操作。"""
            operation["action"] = action
            refresh_button.configure(state=tk.DISABLED)
            connect_button.configure(state=tk.DISABLED)
            forget_button.configure(state=tk.DISABLED)
            progress.start(12)
            status.set(message)

        def set_idle(message):
            """恢复页面操作按钮并显示最终状态。"""
            operation["action"] = None
            refresh_button.configure(state=tk.NORMAL)
            connect_button.configure(state=tk.NORMAL)
            update_forget_button()
            progress.stop()
            status.set(message)

        def clear_pending_results():
            """清除此前页面关闭后残留的后台 Wi-Fi 响应。"""
            try:
                while True:
                    self.wifi_messages.get_nowait()
            except queue.Empty:
                pass

        def request_scan():
            """向后台请求设备重新扫描无线网络。"""
            if operation["action"] is not None:
                return
            clear_pending_results()
            if not self._request_wifi_list():
                status.set("当前没有可用的设备连接")
                return
            set_busy("list", "设备正在扫描附近 Wi-Fi，请稍候……")

        def request_connect():
            """校验输入并向后台提交 Wi-Fi 连接请求。"""
            target_ssid = ssid.get().strip()
            if not target_ssid:
                messagebox.showwarning("Wi-Fi 设置", "请选择或输入 Wi-Fi 名称。", parent=window)
                ssid_entry.focus_set()
                return
            clear_pending_results()
            if not self._request_wifi_connect(target_ssid, password.get()):
                status.set("当前没有可用的设备连接")
                return
            set_busy("connect", "设备正在连接 {}，请稍候……".format(target_ssid))

        def request_forget():
            """确认后请求设备忘记当前选中的已保存网络。"""
            selection = tree.selection()
            network = displayed_networks.get(selection[0]) if selection else None
            if not network or not network.get("saved"):
                messagebox.showwarning("Wi-Fi 设置", "请选择一个已保存的网络。", parent=window)
                return
            target_ssid = network["ssid"]
            if not messagebox.askyesno(
                "忘记网络",
                "确定要忘记已保存的 Wi-Fi“{}”吗？".format(target_ssid),
                parent=window,
            ):
                return
            clear_pending_results()
            if not self._request_wifi_forget(target_ssid):
                status.set("当前没有可用的设备连接")
                return
            set_busy("forget", "正在忘记 {}……".format(target_ssid))

        def update_forget_button():
            """仅在选中已保存网络且页面空闲时启用忘记按钮。"""
            selection = tree.selection()
            network = displayed_networks.get(selection[0]) if selection else None
            enabled = operation["action"] is None and network and network.get("saved")
            forget_button.configure(state=tk.NORMAL if enabled else tk.DISABLED)

        def select_network(event=None):
            """将列表中选中的无线网络名称填入连接表单。"""
            del event
            selection = tree.selection()
            if selection:
                ssid.set(tree.item(selection[0], "values")[0])
                password.set("")
                password_entry.focus_set()
            update_forget_button()

        def show_networks(data):
            """在列表中展示扫描、已保存及已连接的无线网络。"""
            for item_id in tree.get_children():
                tree.delete(item_id)
            displayed_networks.clear()
            networks = merge_wifi_networks(data.get("networks"), data.get("wifi"))
            for network in networks:
                rssi = network.get("rssi")
                signal = "{} dBm".format(rssi) if isinstance(rssi, int) else "--"
                item_id = tree.insert("", tk.END, values=(
                    network["ssid"],
                    wifi_state_label(network),
                    signal,
                    wifi_security_label(network.get("security")),
                ))
                displayed_networks[item_id] = network
            saved_ssid = (data.get("wifi") or {}).get("ssid")
            if saved_ssid:
                ssid.set(saved_ssid)
            return len(networks)

        def poll_results():
            """消费后台 Wi-Fi 结果并刷新页面状态。"""
            try:
                result = self.wifi_messages.get_nowait()
            except queue.Empty:
                result = None
            if result is not None and result.get("action") == operation["action"]:
                if result.get("status") != "ok":
                    set_idle("操作失败：{}".format(result.get("message") or "未知错误"))
                elif result.get("action") == "list":
                    count = show_networks(result.get("data") or {})
                    set_idle("扫描完成，共发现 {} 个 Wi-Fi。".format(count))
                elif result.get("action") == "connect":
                    wifi = (result.get("data") or {}).get("wifi") or {}
                    target = wifi.get("ssid") or ssid.get().strip()
                    ip = wifi.get("ip")
                    set_idle(
                        "已连接 {}{}。".format(target, "，设备地址 {}".format(ip) if ip else "")
                    )
                    request_scan()
                else:
                    forgotten = (result.get("data") or {}).get("forgotten") or ssid.get().strip()
                    ssid.set("")
                    password.set("")
                    set_idle("已忘记 {}。".format(forgotten))
                    request_scan()
            if window.winfo_exists():
                window.after(100, poll_results)

        def close_window():
            """关闭 Wi-Fi 页面并移除父窗口持有的引用。"""
            parent._wifi_settings_window = None
            window.destroy()

        tree.bind("<<TreeviewSelect>>", select_network)
        tree.bind("<Double-1>", select_network)
        refresh_button.configure(command=request_scan)
        connect_button.configure(command=request_connect)
        forget_button.configure(command=request_forget)
        window.protocol("WM_DELETE_WINDOW", close_window)
        poll_results()
        request_scan()
        self._show_centered_tk_window(window)
