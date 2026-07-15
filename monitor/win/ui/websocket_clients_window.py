"""Windows WebSocket 客户端连接记录与准入策略窗口。"""

import queue


class WebSocketClientsWindowMixin:
    """为设备管理窗口提供客户端清单、禁用和优先级编辑页面。"""

    def _show_websocket_clients(self, parent):
        """打开客户端管理页面并立即读取设备端持久化清单。"""
        import tkinter as tk
        from tkinter import messagebox, ttk

        existing = getattr(parent, "_websocket_clients_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        parent._websocket_clients_window = window
        window.withdraw()
        window.title("WebSocket 客户端")
        window.geometry("820x480")
        window.minsize(680, 450)
        window.transient(parent)
        window.attributes("-topmost", True)
        self._set_tk_window_icon(window)

        status = tk.StringVar(master=window, value="正在读取设备客户端清单……")
        ttk.Label(window, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        progress = ttk.Progressbar(window, mode="indeterminate")
        progress.pack(fill=tk.X, padx=16, pady=(0, 10))

        list_frame = ttk.LabelFrame(window, text="连接过设备的 WebSocket 客户端", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        columns = ("name", "state", "priority", "connections", "peer", "id")
        tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=11)
        headings = {
            "name": "设备名称",
            "state": "状态",
            "priority": "优先级",
            "connections": "连接次数",
            "peer": "最近地址",
            "id": "客户端标识",
        }
        widths = {"name": 140, "state": 90, "priority": 70, "connections": 75, "peer": 110, "id": 220}
        for name in columns:
            tree.heading(name, text=headings[name])
            tree.column(name, width=widths[name], anchor=tk.CENTER if name in ("state", "priority", "connections") else tk.W)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        edit_frame = ttk.LabelFrame(window, text="选中客户端策略", padding=10)
        edit_frame.pack(fill=tk.X, padx=16, pady=(0, 12))
        enabled = tk.BooleanVar(master=window, value=True)
        priority = tk.IntVar(master=window, value=0)
        ttk.Checkbutton(edit_frame, text="允许连接", variable=enabled).pack(side=tk.LEFT)
        ttk.Label(edit_frame, text="优先级：").pack(side=tk.LEFT, padx=(20, 4))
        priority_box = ttk.Spinbox(edit_frame, from_=-1000, to=1000, textvariable=priority, width=8)
        priority_box.pack(side=tk.LEFT)
        ttk.Label(edit_frame, text="数值越大，越能抢占低优先级连接").pack(side=tk.LEFT, padx=(12, 0))

        actions = ttk.Frame(window)
        actions.pack(fill=tk.X, padx=16, pady=(0, 16))
        refresh_button = ttk.Button(actions, text="刷新")
        refresh_button.pack(side=tk.LEFT)
        save_button = ttk.Button(actions, text="保存策略", state=tk.DISABLED)
        save_button.pack(side=tk.RIGHT)
        clients = {}
        operation = {"action": None}

        def clear_results():
            """清除窗口上一次打开时遗留的后台响应。"""
            try:
                while True:
                    self.websocket_client_messages.get_nowait()
            except queue.Empty:
                pass

        def set_busy(action, message):
            """进入操作中状态并阻止重复提交。"""
            operation["action"] = action
            refresh_button.configure(state=tk.DISABLED)
            save_button.configure(state=tk.DISABLED)
            progress.start(12)
            status.set(message)

        def set_idle(message):
            """恢复空闲状态和当前选中项的编辑能力。"""
            operation["action"] = None
            refresh_button.configure(state=tk.NORMAL)
            save_button.configure(state=tk.NORMAL if tree.selection() else tk.DISABLED)
            progress.stop()
            status.set(message)

        def request_list():
            """向后台请求最新客户端清单。"""
            if operation["action"] is not None:
                return
            clear_results()
            if not self._request_websocket_client_list():
                status.set("当前没有可用的设备连接")
                return
            set_busy("list", "正在读取设备客户端清单……")

        def select_client(event=None):
            """把选中客户端策略载入编辑控件。"""
            del event
            selection = tree.selection()
            client = clients.get(selection[0]) if selection else None
            if client:
                enabled.set(bool(client.get("enabled", True)))
                priority.set(int(client.get("priority", 0)))
            save_button.configure(
                state=tk.NORMAL if client and operation["action"] is None else tk.DISABLED
            )

        def save_policy():
            """确认必要风险后提交选中客户端的新策略。"""
            selection = tree.selection()
            client = clients.get(selection[0]) if selection else None
            if client is None:
                return
            if client.get("active") and not enabled.get() and not messagebox.askyesno(
                "禁用当前客户端",
                "禁用当前活动客户端会立即断开本 Monitor，确定继续吗？",
                parent=window,
            ):
                return
            try:
                target_priority = int(priority.get())
            except (TypeError, ValueError):
                messagebox.showwarning("WebSocket 客户端", "优先级必须是整数。", parent=window)
                return
            if not -1000 <= target_priority <= 1000:
                messagebox.showwarning("WebSocket 客户端", "优先级必须在 -1000 至 1000 之间。", parent=window)
                return
            clear_results()
            if not self._request_websocket_client_update(client["id"], enabled.get(), target_priority):
                status.set("当前没有可用的设备连接")
                return
            set_busy("update", "正在保存 {} 的连接策略……".format(client.get("name") or client["id"]))

        def show_clients(items):
            """按设备返回顺序重建客户端表格。"""
            for item_id in tree.get_children():
                tree.delete(item_id)
            clients.clear()
            for client in items if isinstance(items, list) else ():
                if not isinstance(client, dict) or not client.get("id"):
                    continue
                if client.get("active"):
                    state = "当前连接"
                elif client.get("enabled", True):
                    state = "允许"
                else:
                    state = "已禁用"
                item_id = tree.insert("", tk.END, values=(
                    client.get("name") or "--",
                    state,
                    client.get("priority", 0),
                    client.get("connections", 0),
                    client.get("last_peer") or "--",
                    client["id"],
                ))
                clients[item_id] = client
            return len(clients)

        def poll_results():
            """消费后台响应并更新清单或编辑结果。"""
            try:
                result = self.websocket_client_messages.get_nowait()
            except queue.Empty:
                result = None
            if result is not None and result.get("action") == operation["action"]:
                if result.get("status") != "ok":
                    set_idle("操作失败：{}".format(result.get("message") or "未知错误"))
                elif operation["action"] == "list":
                    count = show_clients((result.get("data") or {}).get("clients"))
                    set_idle("已记录 {} 个 WebSocket 客户端。".format(count))
                else:
                    set_idle("客户端策略已保存。")
                    request_list()
            if window.winfo_exists():
                window.after(100, poll_results)

        def close_window():
            """关闭页面并移除父窗口引用。"""
            parent._websocket_clients_window = None
            window.destroy()

        tree.bind("<<TreeviewSelect>>", select_client)
        refresh_button.configure(command=request_list)
        save_button.configure(command=save_policy)
        window.protocol("WM_DELETE_WINDOW", close_window)
        poll_results()
        request_list()
        self._show_centered_tk_window(window)
