"""Windows Tk 窗口公共支持能力。"""

import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from build_info import MONITOR_VERSION

LOGGER = logging.getLogger("pico-monitor.windows-update")


class TkSupportMixin:
    """为托盘应用提供独立的窗口实现。"""

    @staticmethod
    def _configure_tk_runtime():
        """为源码运行和单文件运行配置 Tcl/Tk 标准库路径。"""
        roots = []
        for candidate in (
            getattr(sys, "_MEIPASS", None),
            sys.base_prefix,
            sys.prefix,
            sys.exec_prefix,
            Path(sys.executable).resolve().parent if sys.executable else None,
        ):
            if candidate:
                path = Path(candidate)
                if path not in roots:
                    roots.append(path)

        for root in roots:
            tcl_dir = root / "tcl" / "tcl8.6"
            tk_dir = root / "tcl" / "tk8.6"
            if "TCL_LIBRARY" not in os.environ and (tcl_dir / "init.tcl").exists():
                os.environ["TCL_LIBRARY"] = str(tcl_dir)
            if "TK_LIBRARY" not in os.environ and (tk_dir / "tk.tcl").exists():
                os.environ["TK_LIBRARY"] = str(tk_dir)
            if "TCL_LIBRARY" in os.environ and "TK_LIBRARY" in os.environ:
                break

    @staticmethod
    def _center_tk_window(window):
        """将 Tk 窗口固定放置在屏幕中央。"""
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        if width <= 1:
            width = window.winfo_reqwidth()
        if height <= 1:
            height = window.winfo_reqheight()
        x = max(0, (window.winfo_screenwidth() - width) // 2)
        y = max(0, (window.winfo_screenheight() - height) // 2)
        window.geometry("{}x{}+{}+{}".format(width, height, x, y))

    @classmethod
    def _show_centered_tk_window(cls, window):
        """完成窗口居中定位后再显示，避免 Windows 在左上角短暂闪现。"""
        cls._center_tk_window(window)
        window.deiconify()

    def _set_tk_window_icon(self, window):
        """为当前窗口及其后续弹框统一设置托盘程序图标。"""
        import tkinter as tk

        application_icon = tk.PhotoImage(
            master=window,
            file=self._resource_path("icon", "icon.png"),
        )
        window.iconphoto(True, application_icon)
        window.application_icon = application_icon

    def _show_copyable_error_dialog(self, parent, title, message, detail=None):
        """显示带复制按钮的错误弹框，用于保留完整上传失败原因。"""
        import tkinter as tk
        from tkinter import ttk

        title_text = str(title or "错误")
        message_text = str(message or "未知错误")
        detail_text = "" if detail is None else str(detail)
        copy_text = message_text if not detail_text else "{}\n\n{}".format(
            message_text,
            detail_text,
        )

        owner = parent if parent is not None else self.settings_window
        dialog = tk.Toplevel(owner) if owner is not None else tk.Tk()
        dialog.withdraw()
        dialog.title(title_text)
        dialog.resizable(True, True)
        dialog.configure(bg="#f5f7fa")
        dialog.geometry("620x360")
        dialog.minsize(480, 260)
        try:
            if owner is not None:
                dialog.transient(owner)
            dialog.attributes("-topmost", True)
            dialog.grab_set()
        except tk.TclError:
            pass
        try:
            self._set_tk_window_icon(dialog)
        except Exception:
            pass

        container = ttk.Frame(dialog, padding=18)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        ttk.Label(
            container,
            text=title_text,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            container,
            text=message_text,
            foreground="#c0392b",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 8))

        text_box = tk.Text(
            container,
            height=9,
            wrap=tk.WORD,
            relief=tk.SOLID,
            borderwidth=1,
            font=("Consolas", 9),
        )
        scrollbar = ttk.Scrollbar(
            container,
            orient=tk.VERTICAL,
            command=text_box.yview,
        )
        text_box.configure(yscrollcommand=scrollbar.set)
        text_box.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
        text_box.insert("1.0", copy_text)
        text_box.configure(state=tk.DISABLED)

        action_frame = ttk.Frame(container)
        action_frame.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        copy_state = ttk.Label(action_frame, text="", foreground="#67c23a")
        copy_state.pack(side=tk.LEFT, padx=(0, 10))

        def copy_error_content():
            """把完整错误信息复制到系统剪贴板。"""
            dialog.clipboard_clear()
            dialog.clipboard_append(copy_text)
            dialog.update()
            copy_state.configure(text="已复制")

        ttk.Button(
            action_frame,
            text="复制报错内容",
            command=copy_error_content,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            action_frame,
            text="关闭",
            command=dialog.destroy,
        ).pack(side=tk.LEFT)

        dialog.bind("<Escape>", lambda event: dialog.destroy())
        self._show_centered_tk_window(dialog)
        dialog.focus_force()
        dialog.wait_window()

    def _report_unhandled_crash(
        self,
        exception_type,
        exception,
        traceback_object,
        thread_name="托盘主线程",
    ):
        """保存未捕获异常，并显示能够复制完整堆栈的崩溃弹框。"""
        report = "".join(traceback.format_exception(
            exception_type,
            exception,
            traceback_object,
        ))
        crash_directory = self.data_directory / "crash"
        crash_path = crash_directory / datetime.now().strftime(
            "crash_%Y%m%d_%H%M%S_%f.log"
        )
        try:
            crash_directory.mkdir(parents=True, exist_ok=True)
            crash_path.write_text(
                "线程：{}\n版本：{}\n时间：{}\n\n{}".format(
                    thread_name,
                    MONITOR_VERSION,
                    datetime.now().isoformat(timespec="seconds"),
                    report,
                ),
                encoding="utf-8",
            )
        except OSError:
            crash_path = None

        detail = "线程：{}\n{}".format(thread_name, report)
        if crash_path is not None:
            detail = "崩溃日志：{}\n\n{}".format(crash_path, detail)
        LOGGER.critical("Windows 托盘发生未捕获异常\n%s", report)

        # 多个后台线程同时失败时只显示一个模态窗口，避免 Tk 根窗口互相争用。
        if not self.crash_dialog_lock.acquire(False):
            return
        try:
            self._configure_tk_runtime()
            self._show_copyable_error_dialog(
                None,
                "OmniWatch USB监控屏崩溃",
                "应用发生未处理异常，请复制下方崩溃信息并反馈。",
                detail=detail,
            )
        except Exception:
            LOGGER.exception("显示托盘崩溃弹框失败")
        finally:
            self.crash_dialog_lock.release()

    def _install_thread_crash_handler(self):
        """安装后台线程未捕获异常处理器，并返回原处理器。"""
        original_hook = threading.excepthook

        def handle_thread_crash(arguments):
            """把后台线程异常转交给统一崩溃日志与弹框流程。"""
            self._report_unhandled_crash(
                arguments.exc_type,
                arguments.exc_value,
                arguments.exc_traceback,
                getattr(arguments.thread, "name", "后台线程"),
            )

        threading.excepthook = handle_thread_crash
        return original_hook

    @staticmethod
    def _should_use_copyable_custom_style_error(title):
        """判断自定义屏幕弹框中的错误是否需要可复制错误详情。"""
        title_text = str(title or "")
        keywords = ("上传", "样式", "自定义屏幕", "自定义样式")
        return any(keyword in title_text for keyword in keywords)
