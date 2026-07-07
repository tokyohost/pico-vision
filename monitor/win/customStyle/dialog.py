"""实现自定义屏幕样式清单弹框。"""

import queue
import threading


def show_custom_style_dialog(application):
    """在独立界面线程中查询并展示 Pico 自定义样式。"""
    threading.Thread(
        target=_run_custom_style_dialog,
        args=(application,),
        name="自定义屏幕窗口",
        daemon=True,
    ).start()


def _run_custom_style_dialog(application):
    """创建弹框并轮询后台进程返回的样式清单。"""
    application._configure_tk_runtime()
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("自定义屏幕")
    root.geometry("520x360")
    root.minsize(420, 260)
    application._set_tk_window_icon(root)
    status = tk.StringVar(value="正在从 Pico 获取自定义样式清单……")
    ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=16)
    columns = ("name", "chinese_name")
    table = ttk.Treeview(root, columns=columns, show="headings")
    table.heading("name", text="样式标识")
    table.heading("chinese_name", text="中文名称")
    table.column("name", width=200)
    table.column("chinese_name", width=260)
    table.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

    def refresh():
        """清空旧结果并重新向 Pico 发起查询。"""
        for row in table.get_children():
            table.delete(row)
        status.set("正在从 Pico 获取自定义样式清单……")
        if not application.request_custom_style_catalog():
            status.set("Monitor 未运行，无法查询 Pico")

    def poll_result():
        """轮询工作进程消息并更新表格。"""
        try:
            result = application.custom_style_messages.get_nowait()
        except queue.Empty:
            root.after(100, poll_result)
            return
        if result.get("status") != "ok":
            status.set(result.get("message") or "自定义样式清单查询失败")
        else:
            styles = [item for item in result.get("styles", []) if item.get("type") == "custom"]
            for style in styles:
                table.insert("", tk.END, values=(style.get("name", ""), style.get("chinese_name", "")))
            status.set("共找到 {} 个自定义样式".format(len(styles)))
        root.after(100, poll_result)

    ttk.Button(root, text="刷新", command=refresh).pack(pady=(0, 16))
    refresh()
    root.after(100, poll_result)
    root.mainloop()
