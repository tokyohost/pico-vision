"""Windows 自定义数据管理窗口。"""

import logging
import threading
import datetime as dt
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
        """显示自定义数据插件列表并处理导入、测试、删除和查看。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        manager = custom_data.get_manager()
        root = tk.Tk()
        root.withdraw()
        root.title("自定义数据")
        root.geometry("860x560")
        root.minsize(760, 460)
        self._set_tk_window_icon(root)

        status = tk.StringVar(master=root, value="目录：{}".format(manager.custom_directory))
        tk.Label(root, textvariable=status, anchor="w", padx=10, pady=8).pack(fill=tk.X)

        columns = ("plugin", "key", "task", "zh_name", "interval", "environment", "status")
        table = ttk.Treeview(root, columns=columns, show="headings", height=10)
        table.heading("plugin", text="插件")
        table.heading("key", text="JSON Key")
        table.heading("task", text="任务 Key")
        table.heading("zh_name", text="中文名称")
        table.heading("interval", text="间隔(秒)")
        table.heading("environment", text="独立环境")
        table.heading("status", text="状态")
        table.column("plugin", width=150, anchor="w")
        table.column("key", width=110, anchor="w")
        table.column("task", width=160, anchor="w")
        table.column("zh_name", width=120, anchor="w")
        table.column("interval", width=90, anchor="center")
        table.column("environment", width=100, anchor="w")
        table.column("status", width=100, anchor="w")
        table.pack(fill=tk.BOTH, expand=True, padx=10)

        button_frame = tk.Frame(root, padx=10, pady=8)
        button_frame.pack(fill=tk.X)
        output = scrolledtext.ScrolledText(root, height=9, wrap=tk.WORD)
        output.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        path_by_item = {}
        script_by_item = {}
        name_by_item = {}

        def append_log(content):
            """以线程安全方式向底部文本域追加带时间的操作日志。"""
            content = str(content)

            def append():
                """在 Tk 主线程中追加日志并滚动到底部。"""
                timestamp = dt.datetime.now().strftime("%H:%M:%S")
                output.configure(state=tk.NORMAL)
                lines = content.splitlines() or [""]
                for line in lines:
                    output.insert(tk.END, "[{}] {}\n".format(timestamp, line))
                output.see(tk.END)
                output.configure(state=tk.DISABLED)

            root.after(0, append)

        def selected_path():
            """返回当前选中的插件目录，未选中时提示用户。"""
            selection = table.selection()
            if not selection:
                append_log("操作未执行：请先选择一个插件。")
                messagebox.showinfo("自定义数据", "请先选择一个插件", parent=root)
                return None
            return path_by_item.get(selection[0])

        def selected_name():
            """返回当前选中插件的任务英文名。"""
            selection = table.selection()
            if not selection:
                append_log("操作未执行：请先选择一个插件。")
                messagebox.showinfo("自定义数据", "请先选择一个插件", parent=root)
                return None
            name = name_by_item.get(selection[0])
            if name is None:
                append_log("操作未执行：当前条目加载失败，无法执行插件操作。")
                messagebox.showinfo("自定义数据", "当前条目加载失败，请先修复插件", parent=root)
                return None
            return name

        def selected_script_path():
            """返回当前选中插件的入口脚本路径。"""
            selection = table.selection()
            if not selection:
                append_log("操作未执行：请先选择一个插件。")
                messagebox.showinfo("自定义数据", "请先选择一个插件", parent=root)
                return None
            script_path = script_by_item.get(selection[0])
            if script_path is None:
                append_log("操作未执行：当前条目加载失败，无法查看入口源码。")
                messagebox.showinfo("自定义数据", "当前条目加载失败，请先修复插件", parent=root)
                return None
            return script_path

        def refresh(log_operation=True):
            """刷新插件列表和加载错误。"""
            if log_operation:
                append_log("正在刷新插件列表……")
            path_by_item.clear()
            script_by_item.clear()
            name_by_item.clear()
            for item in table.get_children():
                table.delete(item)
            items, errors = manager.list_items()
            for state in items:
                definition = state.definition
                if not state.runtime_enabled:
                    status_text = "未运行"
                elif state.error:
                    status_text = "执行错误"
                else:
                    status_text = "正常"
                item = table.insert("", tk.END, values=(
                    definition.plugin_directory.name,
                    definition.key,
                    definition.task_name,
                    definition.zh_name,
                    "{:g}".format(definition.interval),
                    manager.environment_status(definition),
                    status_text,
                ))
                path_by_item[item] = definition.plugin_directory
                script_by_item[item] = definition.path
                name_by_item[item] = definition.name
            for script_path, error in errors.items():
                item = table.insert("", tk.END, values=(Path(script_path).name, "加载失败", "-", "-", "-", "-", error))
                path_by_item[item] = Path(script_path)
            status.set("目录：{}    已加载：{}，错误：{}".format(manager.custom_directory, len(items), len(errors)))
            if errors:
                append_log("刷新完成：已加载 {} 个插件，发现 {} 个加载错误。".format(len(items), len(errors)))
                for script_path, error in errors.items():
                    append_log("加载错误 [{}]：{}".format(Path(script_path).name, error))
            else:
                append_log("刷新完成：已加载 {} 个插件，未发现加载错误。".format(len(items)))

        def load_plugin():
            """选择 ZIP 插件包并导入。"""
            script_path = filedialog.askopenfilename(
                parent=root,
                title="加载自定义数据插件",
                filetypes=(("ZIP 插件包", "*.zip"),),
            )
            if not script_path:
                append_log("已取消加载 ZIP 插件包。")
                return
            append_log("开始加载文件：{}".format(script_path))
            try:
                definition = import_plugin_with_overwrite_confirm(script_path, "ZIP 插件包")
                if definition is None:
                    return
                append_log("导入成功：{}；key={}；task={}；中文名称={}；间隔={:g}s。".format(
                    definition.plugin_directory.name,
                    definition.key,
                    definition.task_name,
                    definition.zh_name,
                    definition.interval,
                ))
                append_log("插件当前为未运行状态；请选中插件安装依赖，准备好后单击“立即运行”。")
                refresh(log_operation=False)
            except Exception as error:
                append_log("加载失败：{}".format(error))

        def import_plugin_with_overwrite_confirm(source_path, source_label):
            """导入插件，遇到重复 key 或任务名时询问用户是否覆盖。"""
            try:
                return manager.import_plugin(source_path)
            except custom_data.CustomDataDuplicateError as error:
                conflict_text = "\n".join(
                    " - {}（key={}，task={}）".format(conflict.zh_name, conflict.key, conflict.task_name)
                    for conflict in error.conflicts
                )
                if not conflict_text:
                    conflict_text = " - 目标插件目录已存在，但当前没有成功加载到列表中"
                message = (
                    "检测到重复的自定义数据插件：\n{}\n\n"
                    "是否覆盖已安装插件？覆盖会删除旧插件目录及其独立环境。"
                ).format(conflict_text)
                append_log("{} 重复：{}".format(source_label, error))
                if not messagebox.askyesno("覆盖自定义数据插件", message, parent=root):
                    append_log("已取消覆盖：{}。".format(source_path))
                    return None
                append_log("用户确认覆盖重复插件，正在重新导入：{}。".format(source_path))
                return manager.import_plugin(source_path, overwrite=True)

        def load_directory():
            """选择包含 plugin.json 的本地插件目录并导入。"""
            plugin_directory = filedialog.askdirectory(parent=root, title="选择自定义数据插件目录")
            if not plugin_directory:
                append_log("已取消加载目录。")
                return
            append_log("开始加载插件目录：{}".format(plugin_directory))
            try:
                definition = import_plugin_with_overwrite_confirm(plugin_directory, "插件目录")
                if definition is None:
                    return
                append_log("目录导入成功：{}（{}）。".format(definition.zh_name, definition.task_name))
                append_log("插件当前为未运行状态；请选中插件安装依赖，准备好后单击“立即运行”。")
                refresh(log_operation=False)
            except Exception as error:
                append_log("目录加载失败：{}".format(error))

        def activate_plugin():
            """将未运行插件实时加入后台 Monitor 采集任务。"""
            name = selected_name()
            if name is None:
                return
            try:
                definition = manager.activate_plugin(name)
                if not self._activate_custom_data_plugin(name):
                    append_log("插件 {} 已标记为运行；后台 Monitor 未运行，请下次启动后自动生效。".format(name))
                    messagebox.showinfo("自定义数据", "后台 Monitor 未运行，插件将在下次启动时运行。", parent=root)
                else:
                    append_log("插件 {} 已实时加入 Monitor 采集任务。".format(definition.task_name))
                refresh(log_operation=False)
            except Exception as error:
                append_log("实时运行失败：{}".format(error))
                messagebox.showerror("自定义数据", "实时运行失败：{}".format(error), parent=root)

        def install_dependencies():
            """在后台创建所选插件的独立环境并安装依赖。"""
            name = selected_name()
            if name is None:
                return
            append_log("开始为插件 {} 创建独立环境并安装依赖。".format(name))

            def worker():
                """执行耗时安装任务，并在结束后刷新界面。"""
                try:
                    result = manager.install_dependencies(name, append_log)
                    append_log("插件 {} 安装完成：{}。".format(name, result))
                except Exception as error:
                    append_log("插件 {} 安装失败：{}".format(name, error))
                finally:
                    root.after(0, lambda: refresh(log_operation=False))

            threading.Thread(target=worker, name="自定义数据依赖安装", daemon=True).start()

        def test_script():
            """测试执行当前选中脚本并展示 JSON 或异常详情。"""
            name = selected_name()
            if name is None:
                return
            append_log("开始测试插件：{}。".format(name))

            def worker():
                """在后台执行插件测试，避免采集期间阻塞管理窗口。"""
                result = manager.test_plugin(name)
                append_log("插件 {} 测试结果：\n{}".format(name, result))
                root.after(0, lambda: refresh(log_operation=False))

            threading.Thread(target=worker, name="自定义数据插件测试", daemon=True).start()

        def delete_plugin():
            """删除当前选中的插件目录及其独立虚拟环境。"""
            plugin_path = selected_path()
            if plugin_path is None:
                return
            if not messagebox.askyesno("删除自定义数据插件", "确认删除插件 {} 及其独立环境？".format(Path(plugin_path).name), parent=root):
                append_log("已取消删除：{}。".format(Path(plugin_path).name))
                return
            append_log("开始删除插件：{}。".format(Path(plugin_path).name))
            try:
                manager.delete_plugin(plugin_path)
                append_log("删除成功：{}。".format(Path(plugin_path).name))
                refresh(log_operation=False)
            except Exception as error:
                append_log("删除失败：{}".format(error))

        def view_script():
            """在只读窗口中查看当前选中脚本源码。"""
            script_path = selected_script_path()
            if script_path is None:
                return
            append_log("正在查看插件入口源码：{}。".format(script_path))
            window = tk.Toplevel(root)
            window.withdraw()
            window.title("查看 - {}".format(Path(script_path).name))
            window.geometry("760x520")
            self._set_tk_window_icon(window)
            text_box = scrolledtext.ScrolledText(window, wrap=tk.NONE)
            text_box.pack(fill=tk.BOTH, expand=True)
            try:
                text_box.insert(tk.END, Path(script_path).read_text(encoding="utf-8"))
                append_log("源码窗口已打开：{}。".format(Path(script_path).name))
            except Exception as error:
                text_box.insert(tk.END, "读取失败：{}".format(error))
                append_log("源码读取失败：{}".format(error))
            text_box.configure(state=tk.DISABLED)
            self._show_centered_tk_window(window)

        ttk.Button(button_frame, text="加载 ZIP", command=load_plugin).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="加载目录", command=load_directory).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="安装依赖", command=install_dependencies).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="立即运行", command=activate_plugin).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="测试", command=test_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="删除", command=delete_plugin).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="查看", command=view_script).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_frame, text="刷新", command=refresh).pack(side=tk.LEFT)
        output.configure(state=tk.DISABLED)
        append_log("自定义数据管理页面已打开，插件目录：{}。".format(manager.custom_directory))
        refresh()
        self._show_centered_tk_window(root)
        root.mainloop()
