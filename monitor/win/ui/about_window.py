"""Windows 关于应用窗口。"""

import logging
import threading

from build_info import MONITOR_VERSION

from ..constants import APPLICATION_NAME

LOGGER = logging.getLogger("pico-monitor.windows-update")


class AboutWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

    def _show_about(self, icon=None, item=None):
        """在独立线程中打开唯一的关于应用窗口。"""
        del icon, item
        with self.about_window_lock:
            if self.about_window_open:
                return
            self.about_window_open = True
        threading.Thread(
            target=self._run_about_window_guarded,
            name="关于应用窗口",
            daemon=True,
        ).start()

    def _run_about_window_guarded(self):
        """运行关于窗口，并在窗口退出后恢复可打开状态。"""
        try:
            self._run_about_window()
        except Exception as error:
            LOGGER.exception("打开关于应用窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开关于应用窗口，请查看日志", APPLICATION_NAME)
        finally:
            with self.about_window_lock:
                self.about_window_open = False

    def _run_about_window(self):
        """显示版本、作者、联系方式和店铺二维码。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.title("关于应用")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        self._set_tk_window_icon(root)
        frame = tk.Frame(root, padx=24, pady=18)
        frame.pack()
        tk.Label(frame, text=APPLICATION_NAME, font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(0, 8))
        tk.Label(frame, text="版本号：{}".format(MONITOR_VERSION)).pack(anchor="w", pady=2)
        tk.Label(frame, text="作者：tokyohost").pack(anchor="w", pady=2)
        tk.Label(frame, text="微信号：hi2024FL").pack(anchor="w", pady=2)
        tk.Label(frame, text="咸鱼店铺二维码：").pack(anchor="w", pady=(10, 4))
        image_path = self._resource_path("assert", "fishQr.png")
        with Image.open(image_path) as source:
            qr_image = source.convert("RGB").resize((220, 220), Image.Resampling.LANCZOS)
        # 显式绑定当前窗口的 Tcl 解释器，避免其他 Tk 线程创建过默认根窗口后跨线程复用。
        photo = ImageTk.PhotoImage(qr_image, master=root)
        image_label = tk.Label(frame, image=photo)
        image_label.image = photo
        image_label.pack()
        tk.Button(frame, text="确定", width=12, command=root.destroy).pack(pady=(14, 0))
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        self._center_tk_window(root)
        root.mainloop()
