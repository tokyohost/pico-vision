"""Windows 自定义屏幕管理窗口。"""


class CustomStyleWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

    def _show_custom_style(self, icon=None, item=None):
        """打开自定义屏幕弹框，并通过后台进程向 Pico 获取最新清单。"""
        del icon, item
        import tkinter.messagebox as messagebox

        from ..customStyle.dialog import show_custom_style_dialog

        original_showerror = messagebox.showerror

        def showerror_with_copy(title=None, message=None, **options):
            """在自定义屏幕窗口内把上传失败弹框替换为可复制版本。"""
            if self._should_use_copyable_custom_style_error(title):
                parent = options.get("parent") or self.settings_window
                detail = options.get("detail")
                if detail is None and isinstance(message, BaseException):
                    detail = repr(message)
                self._show_copyable_error_dialog(
                    parent,
                    title or "上传样式失败",
                    message or "未知错误",
                    detail=detail,
                )
                return "ok"
            return original_showerror(title, message, **options)

        messagebox.showerror = showerror_with_copy
        try:
            show_custom_style_dialog(self)
        finally:
            if messagebox.showerror is showerror_with_copy:
                messagebox.showerror = original_showerror
