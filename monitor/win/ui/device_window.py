"""Windows 设备管理窗口。"""

import logging
import os
import queue
import subprocess
import threading
from datetime import datetime

from ..constants import APPLICATION_NAME

LOGGER = logging.getLogger("pico-monitor.windows-update")


class DeviceWindowMixin:
    """为托盘应用提供独立的窗口实现。"""

    def _show_device_probe(self, icon=None, item=None):
        """在独立线程中打开唯一的设备管理窗口。"""
        del icon, item
        with self.device_probe_window_lock:
            if self.device_probe_window_open:
                return
            self.device_probe_window_open = True
        threading.Thread(
            target=self._run_device_probe_window_guarded,
            name="设备探测窗口",
            daemon=True,
        ).start()

    def _run_device_probe_window_guarded(self):
        """运行设备管理窗口，并在窗口退出后恢复可打开状态。"""
        try:
            self._run_device_probe_window()
        except Exception as error:
            LOGGER.exception("打开设备探测窗口失败：%s", error)
            if self.icon is not None:
                self.icon.notify("无法打开设备探测窗口，请查看日志", APPLICATION_NAME)
        finally:
            with self.device_probe_window_lock:
                self.device_probe_window_open = False

    def _run_device_probe_window(self):
        """展示已连接设备信息，并提供带等待进度的设备重启操作。"""
        self._configure_tk_runtime()
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("设备管理")
        root.geometry("720x520")
        root.minsize(560, 320)
        root.attributes("-topmost", True)
        self._set_tk_window_icon(root)

        # 显式绑定当前窗口的 Tcl 解释器，避免多个独立 Tk 线程共享默认根窗口。
        status = tk.StringVar(master=root, value="正在探测 OmniWatch 设备，请稍候……")
        ttk.Label(root, textvariable=status).pack(fill=tk.X, padx=16, pady=(16, 8))
        progress = ttk.Progressbar(root, mode="indeterminate")
        progress.pack(fill=tk.X, padx=16, pady=(0, 12))
        progress.start(12)

        device_panel = ttk.LabelFrame(root, text="当前已连接设备", padding=12)
        device_panel.pack(fill=tk.X, padx=16, pady=(0, 12))
        device_labels = {
            "board_model": "开发板型号",
            "screen_color_profile": "屏幕色彩方案",
            "firmware_version": "固件版本",
            "screen_resolution": "屏幕分辨率",
        }
        device_values = {
            "board_model": tk.StringVar(master=root, value="未连接"),
            "screen_color_profile": tk.StringVar(master=root, value="--"),
            "firmware_version": tk.StringVar(master=root, value="--"),
            "screen_resolution": tk.StringVar(master=root, value="--"),
        }
        for row, (field_name, value) in enumerate(device_values.items()):
            ttk.Label(
                device_panel,
                text=device_labels[field_name] + "：",
                width=20,
            ).grid(
                row=row, column=0, sticky=tk.W, pady=2
            )
            ttk.Label(device_panel, textvariable=value).grid(
                row=row, column=1, sticky=tk.W, pady=2
            )

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, padx=16, pady=(0, 12))
        probe_button = ttk.Button(action_frame, text="主动探测")
        probe_button.pack(side=tk.LEFT)
        reboot_button = ttk.Button(action_frame, text="重启设备", state=tk.DISABLED)
        reboot_button.pack(side=tk.RIGHT)

        log_frame = ttk.Frame(root)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Microsoft YaHei UI", 9),
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_text.yview)
        log_text.configure(yscrollcommand=scrollbar.set)
        log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        messages = queue.Queue()
        reboot_state = {"started": None}
        initial_connection = self._get_device_connection()

        def clear_connected_device():
            """清空已连接设备信息，并禁用依赖有效串口的重启操作。"""
            device_values["board_model"].set("未连接")
            device_values["screen_color_profile"].set("--")
            device_values["firmware_version"].set("--")
            device_values["screen_resolution"].set("--")
            reboot_button.configure(state=tk.DISABLED)

        def refresh_connection_state():
            """消费后台串口状态事件，实时同步设备面板和操作按钮。"""
            try:
                while True:
                    connection = self.device_connection_messages.get_nowait()
                    if not connection.get("connected"):
                        clear_connected_device()
                        status.set("当前没有已连接设备")
                        continue
                    device_values["board_model"].set(
                        connection.get("board_model") or "未知"
                    )
                    device_values["screen_color_profile"].set(
                        connection.get("screen_color_profile") or "未知"
                    )
                    device_values["firmware_version"].set(
                        connection.get("firmware_version") or "未知"
                    )
                    device_values["screen_resolution"].set(
                        connection.get("screen_resolution") or "未知"
                    )
                    reboot_button.configure(state=tk.NORMAL)
                    status.set("设备已连接")
            except queue.Empty:
                pass
            if root.winfo_exists():
                root.after(100, refresh_connection_state)

        def append_log(content):
            """向只读文本域追加日志，并自动滚动到最新内容。"""
            log_text.configure(state=tk.NORMAL)
            log_text.insert(tk.END, content)
            log_text.see(tk.END)
            log_text.configure(state=tk.DISABLED)

        def refresh_messages():
            """消费探测线程消息，并更新进度条及最终状态。"""
            try:
                while True:
                    message_type, content = messages.get_nowait()
                    if message_type == "log":
                        append_log(content)
                        normalized = content.strip()
                        for field_name, value in device_values.items():
                            prefix = "OmniWatch " + device_labels[field_name] + "："
                            if normalized.startswith(prefix):
                                value.set(normalized[len(prefix):].strip() or "未知")
                    else:
                        progress.stop()
                        progress.configure(mode="determinate", maximum=100, value=100)
                        success = content == 0
                        status.set("设备信息加载完成" if success else "未探测到可用设备")
                        reboot_button.configure(state=tk.NORMAL if success else tk.DISABLED)
                        probe_button.configure(state=tk.NORMAL)
                        if not success:
                            clear_connected_device()
            except queue.Empty:
                pass
            if root.winfo_exists():
                root.after(100, refresh_messages)

        def refresh_reboot_progress():
            """刷新重启等待进度，并处理设备确认或三十秒超时。"""
            started = reboot_state["started"]
            if started is None:
                return
            try:
                result = self.device_management_messages.get_nowait()
            except queue.Empty:
                result = None
            elapsed = (datetime.now() - started).total_seconds()
            if result is not None:
                reboot_state["started"] = None
                progress.stop()
                progress.configure(mode="determinate", maximum=100, value=100)
                status.set(result.get("message") or "设备已回复")
                append_log((result.get("message") or "设备已回复") + "\n")
                clear_connected_device()
                if not self.stopping.is_set():
                    process = self.worker_process
                    if process is not None and process.poll() is None:
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    self._start_worker()
                return
            if elapsed >= 30:
                reboot_state["started"] = None
                progress.configure(value=30)
                status.set("设备无响应，请重新拔插设备注册")
                append_log("设备无响应，请重新拔插设备注册\n")
                reboot_button.configure(state=tk.NORMAL)
                if not self.stopping.is_set():
                    threading.Thread(
                        target=self._restart_worker,
                        name="设备重启超时恢复",
                        daemon=True,
                    ).start()
                return
            progress.configure(value=elapsed)
            root.after(100, refresh_reboot_progress)

        def reboot_device():
            """向后台 Monitor 发送重启指令并启动三十秒响应等待。"""
            process = self.worker_process
            if process is None or process.poll() is not None or process.stdin is None:
                status.set("当前没有已连接设备")
                return
            while not self.device_management_messages.empty():
                self.device_management_messages.get_nowait()
            try:
                process.stdin.write("EXIT_REBOOT\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                status.set("重启指令发送失败")
                return
            reboot_button.configure(state=tk.DISABLED)
            progress.stop()
            progress.configure(mode="determinate", maximum=30, value=0)
            status.set("重启指令已发送，正在等待设备回复……")
            append_log("重启指令已发送，最长等待 30 秒。\n")
            reboot_state["started"] = datetime.now()
            refresh_reboot_progress()

        reboot_button.configure(command=reboot_device)

        def show_connected_device(connection):
            """将已连接设备快照显示到设备管理面板。"""
            for field_name, value in device_values.items():
                value.set(connection.get(field_name) or "未知")
            reboot_button.configure(state=tk.NORMAL)
            progress.stop()
            progress.configure(mode="determinate", maximum=100, value=100)
            status.set("设备已连接")

        def perform_probe():
            """暂停常驻监控，执行单次设备探测并在结束后恢复监控。"""
            worker_process = self.worker_process
            if worker_process is not None and worker_process.poll() is None:
                messages.put(("log", "检测到当前设备连接，正在断开……\n"))
                self._stop_worker()
                messages.put(("log", "当前设备连接已断开，开始重新探测。\n"))
            else:
                messages.put(("log", "当前没有已连接设备，开始探测。\n"))
            self.worker_process = None
            process = None
            try:
                process = subprocess.Popen(
                    self._device_probe_command(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=0x08000000,
                    env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1"),
                )
                for line in process.stdout:
                    messages.put(("log", line))
                messages.put(("done", process.wait()))
            except OSError as error:
                messages.put(("log", "启动设备探测失败：{}\n".format(error)))
                messages.put(("done", 1))
            finally:
                if not self.stopping.is_set():
                    self._start_worker()

        def start_probe():
            """启动主动设备探测线程，避免阻塞设备管理窗口。"""
            probe_button.configure(state=tk.DISABLED)
            reboot_button.configure(state=tk.DISABLED)
            status.set("正在主动探测 OmniWatch 设备，请稍候……")
            progress.configure(mode="indeterminate")
            progress.start(12)
            device_values["board_model"].set("探测中……")
            device_values["screen_color_profile"].set("--")
            device_values["firmware_version"].set("--")
            device_values["screen_resolution"].set("--")
            threading.Thread(
                target=perform_probe,
                name="设备主动探测",
                daemon=True,
            ).start()

        probe_button.configure(command=start_probe)
        if initial_connection.get("connected"):
            show_connected_device(initial_connection)
        else:
            start_probe()
        refresh_messages()
        refresh_connection_state()
        self._center_tk_window(root)
        root.mainloop()
