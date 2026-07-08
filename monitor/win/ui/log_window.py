"""Windows 实时日志窗口。"""

import logging
import threading

from ..constants import APPLICATION_NAME

LOGGER = logging.getLogger("pico-monitor.windows-update")


class LogWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

    def _show_log(self, icon=None, item=None):
        """在应用内打开唯一的实时日志查看窗口。"""
        del icon, item
        with self.log_window_lock:
            if self.log_window_open:
                return
            self.log_window_open = True
        threading.Thread(
            target=self._run_log_window_guarded,
            name="日志窗口",
            daemon=True,
        ).start()

    def _run_log_window_guarded(self):
        """运行日志窗口，并在关闭后恢复窗口可打开状态。"""
        try:
            self._run_log_window()
        except Exception as error:
            LOGGER.exception("打开日志窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开日志窗口，请稍后重试", APPLICATION_NAME)
        finally:
            with self.log_window_lock:
                self.log_window_open = False

    def _run_log_window(self):
        """创建支持复制、自动刷新和导出的日志文本窗口。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import messagebox, ttk

        root = tk.Tk()
        root.withdraw()
        root.title("系统监控日志")
        root.geometry("900x600")
        root.minsize(620, 380)
        self._set_tk_window_icon(root)

        status = tk.StringVar(master=root, value="正在加载日志……")
        ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        text_frame = ttk.Frame(root)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        log_text = tk.Text(
            text_frame,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        vertical_scrollbar = ttk.Scrollbar(
            text_frame,
            orient=tk.VERTICAL,
            command=log_text.yview,
        )
        horizontal_scrollbar = ttk.Scrollbar(
            text_frame,
            orient=tk.HORIZONTAL,
            command=log_text.xview,
        )
        log_text.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        log_text.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        state = {"content": None}

        def refresh_log():
            """读取最近日志，并在用户位于末尾时保持自动滚动。"""
            content = self._read_recent_log().decode("utf-8", errors="replace")
            if content != state["content"]:
                at_end = log_text.yview()[1] >= 0.999
                log_text.configure(state=tk.NORMAL)
                log_text.delete("1.0", tk.END)
                log_text.insert("1.0", content)
                log_text.configure(state=tk.DISABLED)
                if at_end or state["content"] is None:
                    log_text.see(tk.END)
                state["content"] = content
                status.set("已加载最近 {:,} 字节日志".format(len(content.encode("utf-8"))))
            if root.winfo_exists():
                root.after(1000, refresh_log)

        def copy_all():
            """把当前文本域中的全部日志复制到系统剪贴板。"""
            root.clipboard_clear()
            root.clipboard_append(log_text.get("1.0", "end-1c"))
            status.set("日志已复制到剪贴板")

        def export_log():
            """调用统一导出逻辑并向用户反馈结果。"""
            try:
                export_path = self._export_log()
            except OSError as error:
                messagebox.showerror("导出日志", str(error), parent=root)
                return
            status.set("日志已导出：{}".format(export_path.name))

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(action_frame, text="复制全部", command=copy_all).pack(side=tk.LEFT)
        ttk.Button(action_frame, text="导出日志", command=export_log).pack(side=tk.RIGHT)
        refresh_log()
        self._show_centered_tk_window(root)
        root.mainloop()
