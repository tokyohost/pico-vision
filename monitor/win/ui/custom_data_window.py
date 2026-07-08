"""Windows 自定义数据管理窗口。"""

import logging
import threading
from pathlib import Path

import custom_data

from ..constants import APPLICATION_NAME

LOGGER = logging.getLogger("pico-monitor.windows-update")


class CustomDataWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

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

        columns = ("file", "key", "task", "zh_name", "interval", "status")
        table = ttk.Treeview(root, columns=columns, show="headings", height=10)
        table.heading("file", text="文件")
        table.heading("key", text="JSON Key")
        table.heading("task", text="任务 Key")
        table.heading("zh_name", text="中文名称")
        table.heading("interval", text="间隔(秒)")
        table.heading("status", text="状态")
        table.column("file", width=220, anchor="w")
        table.column("key", width=110, anchor="w")
        table.column("task", width=160, anchor="w")
        table.column("zh_name", width=120, anchor="w")
        table.column("interval", width=90, anchor="center")
        table.column("status", width=160, anchor="w")
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
                    definition.task_name,
                    definition.zh_name,
                    "{:g}".format(definition.interval),
                    status_text,
                ))
                path_by_item[item] = definition.path
            for script_path, error in errors.items():
                item = table.insert("", tk.END, values=(Path(script_path).name, "加载失败", "-", "-", "-", error))
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
                write_output("加载成功：{}\nkey={}\ntask={}\nzh_name={}\ninterval={:g}s".format(
                    definition.path.name,
                    definition.key,
                    definition.task_name,
                    definition.zh_name,
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
