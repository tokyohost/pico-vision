"""实现自定义屏幕样式清单弹框。"""

import queue
import threading
import webbrowser


CUSTOM_STYLE_TUTORIAL_URL = "https://github.com/tokyohost/omniwatch-doc"


def _format_flash_size(size):
    """把 Flash 字节数格式化为便于阅读的容量文本。"""
    size = max(0, int(size or 0))
    if size >= 1024 * 1024:
        return "{:.2f} MB".format(size / (1024 * 1024))
    if size >= 1024:
        return "{:.1f} KB".format(size / 1024)
    return "{} B".format(size)


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
    from tkinter import filedialog, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("自定义屏幕")
    root.geometry("760x680")
    root.minsize(680, 560)
    application._set_tk_window_icon(root)
    status = tk.StringVar(master=root, value="正在从 OmniWatch 获取自定义样式清单……")
    ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=16)
    flash_status = tk.StringVar(master=root, value="Flash 空间：正在获取……")
    ttk.Label(root, textvariable=flash_status).pack(fill=tk.X, padx=16, pady=(0, 12))
    columns = ("name", "chinese_name", "filename", "file_size", "action")
    table = ttk.Treeview(root, columns=columns, show="headings")
    table.heading("name", text="样式标识")
    table.heading("chinese_name", text="中文名称")
    table.heading("filename", text="模板文件名")
    table.heading("file_size", text="模板文件大小")
    table.heading("action", text="操作")
    table.column("name", width=110)
    table.column("chinese_name", width=130)
    table.column("filename", width=165)
    table.column("file_size", width=95, anchor=tk.E)
    table.column("action", width=70, anchor=tk.CENTER)
    table.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
    existing_style_names = set()

    log_frame = ttk.LabelFrame(root, text="上传日志")
    log_frame.pack(fill=tk.BOTH, padx=16, pady=(0, 12))
    upload_log = scrolledtext.ScrolledText(
        log_frame, height=9, wrap=tk.WORD, state=tk.DISABLED,
    )
    upload_log.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def append_upload_log(message):
        """向只读日志文本域追加一行上传过程日志并滚动到底部。"""
        upload_log.configure(state=tk.NORMAL)
        upload_log.insert(tk.END, str(message).rstrip("\r\n") + "\n")
        upload_log.see(tk.END)
        upload_log.configure(state=tk.DISABLED)

    def clear_upload_logs():
        """清空界面日志和队列中上一次上传遗留的日志。"""
        upload_log.configure(state=tk.NORMAL)
        upload_log.delete("1.0", tk.END)
        upload_log.configure(state=tk.DISABLED)
        while True:
            try:
                application.custom_style_upload_logs.get_nowait()
            except queue.Empty:
                break

    def refresh():
        """清空旧结果并重新向 Pico 发起查询。"""
        for row in table.get_children():
            table.delete(row)
        status.set("正在从 OmniWatch 获取自定义样式清单……")
        flash_status.set("Flash 空间：正在获取……")
        if not application.request_custom_style_catalog():
            status.set("OmniWatch 未运行，无法查询设备")
            flash_status.set("Flash 空间：无法获取")

    def poll_result():
        """轮询工作进程消息并更新表格。"""
        try:
            result = application.custom_style_messages.get_nowait()
        except queue.Empty:
            root.after(100, poll_result)
            return
        if result.get("status") != "ok":
            status.set(result.get("message") or "自定义样式清单查询失败")
            flash_status.set("Flash 空间：无法获取")
        else:
            styles = [item for item in result.get("styles", []) if item.get("type") == "custom"]
            flash = result.get("flash") or {}
            existing_style_names.clear()
            for style in styles:
                existing_style_names.add(style.get("name", ""))
                table.insert("", tk.END, values=(
                    style.get("name", ""),
                    style.get("chinese_name", ""),
                    style.get("filename", ""),
                    _format_flash_size(style.get("file_size")),
                    "删除",
                ))
            status.set("共找到 {} 个自定义样式".format(len(styles)))
            flash_status.set("Flash 空间：{} / {}（剩余空间 / 总大小）".format(
                _format_flash_size(flash.get("free_bytes")),
                _format_flash_size(flash.get("total_bytes")),
            ))
        root.after(100, poll_result)

    def upload_style():
        """选择、校验并上传一个不与 Pico 现有文件重名的样式。"""
        path = filedialog.askopenfilename(
            parent=root,
            title="选择自定义屏幕样式",
            filetypes=(("Python 样式文件", "*.py"),),
        )
        if not path:
            return
        upload_button.configure(state=tk.DISABLED)
        clear_upload_logs()
        append_upload_log("开始校验上传文件：{}".format(path))
        try:
            try:
                validated = application.request_custom_style_upload(
                    path, existing_style_names,
                )
            except FileExistsError as error:
                if not messagebox.askyesno(
                    "覆盖样式",
                    "{}。\n是否覆盖并继续上传？".format(error),
                    parent=root,
                ):
                    status.set("已取消覆盖上传")
                    append_upload_log("用户取消覆盖上传。")
                    upload_button.configure(state=tk.NORMAL)
                    return
                validated = application.request_custom_style_upload(
                    path, existing_style_names, overwrite=True,
                )
        except (OSError, RuntimeError, ValueError) as error:
            append_upload_log("上传请求失败：{}".format(error))
            upload_button.configure(state=tk.NORMAL)
            messagebox.showerror("上传样式", str(error), parent=root)
            return
        append_upload_log("文件校验通过，已提交上传任务：{}".format(validated.filename))
        status.set("正在上传 {}（{}）……".format(
            validated.chinese_name,
            validated.filename,
        ))

    def poll_upload_result():
        """轮询样式上传结果，成功后刷新 Pico 自定义样式清单。"""
        try:
            result = application.custom_style_upload_messages.get_nowait()
        except queue.Empty:
            root.after(100, poll_upload_result)
            return
        if result.get("status") == "ok":
            append_upload_log("上传完成。")
            status.set("样式上传成功，正在刷新清单……")
            refresh()
        else:
            append_upload_log("上传失败：{}".format(
                result.get("message") or "未知错误",
            ))
            messagebox.showerror(
                "上传样式",
                result.get("message") or "自定义样式上传失败",
                parent=root,
            )
            status.set("样式上传失败")
        upload_button.configure(state=tk.NORMAL)
        root.after(100, poll_upload_result)

    def poll_upload_logs():
        """轮询后台上传日志队列并实时追加到日志文本域。"""
        while True:
            try:
                message = application.custom_style_upload_logs.get_nowait()
            except queue.Empty:
                break
            append_upload_log(message)
        root.after(100, poll_upload_logs)

    def delete_selected_style(event):
        """点击删除单元格后确认并提交对应样式删除请求。"""
        if table.identify_region(event.x, event.y) != "cell":
            return
        if table.identify_column(event.x) != "#5":
            return
        row = table.identify_row(event.y)
        values = table.item(row, "values") if row else ()
        if len(values) < 3:
            return
        style_name, chinese_name, filename = values[:3]
        if not messagebox.askyesno(
            "删除样式",
            "确定删除 {}（{}）？\nOmniWatch 删除后将自动重启。".format(
                chinese_name, filename,
            ),
            parent=root,
        ):
            return
        try:
            application.request_custom_style_delete(style_name, filename)
        except RuntimeError as error:
            messagebox.showerror("删除样式", str(error), parent=root)
            return
        status.set("正在删除 {}，等待 OmniWatch 重启……".format(filename))

    def poll_delete_result():
        """轮询删除结果，并在 Pico 重启后重新读取样式清单。"""
        try:
            result = application.custom_style_delete_messages.get_nowait()
        except queue.Empty:
            root.after(100, poll_delete_result)
            return
        if result.get("status") == "ok":
            status.set("样式已删除，OmniWatch 正在重启并更新候选项……")
            root.after(4000, refresh)
        else:
            messagebox.showerror(
                "删除样式",
                result.get("message") or "自定义样式删除失败",
                parent=root,
            )
            status.set("样式删除失败")
        root.after(100, poll_delete_result)

    def open_custom_style_tutorial(_event=None):
        """使用系统默认浏览器打开自定义屏幕教程。"""
        webbrowser.open_new_tab(CUSTOM_STYLE_TUTORIAL_URL)

    action_frame = ttk.Frame(root)
    action_frame.pack(fill=tk.X, padx=16, pady=(0, 16))
    upload_button = ttk.Button(action_frame, text="上传文件", command=upload_style)
    upload_button.pack(side=tk.LEFT)
    ttk.Button(action_frame, text="刷新", command=refresh).pack(side=tk.RIGHT)
    tutorial_link = tk.Label(
        root,
        text="自定义屏幕教程",
        fg="#0563C1",
        cursor="hand2",
        font=("TkDefaultFont", 9, "underline"),
    )
    tutorial_link.pack(anchor=tk.W, padx=16, pady=(0, 12))
    tutorial_link.bind("<Button-1>", open_custom_style_tutorial)
    table.bind("<ButtonRelease-1>", delete_selected_style)
    refresh()
    root.after(100, poll_result)
    root.after(100, poll_upload_result)
    root.after(100, poll_upload_logs)
    root.after(100, poll_delete_result)
    root.mainloop()
