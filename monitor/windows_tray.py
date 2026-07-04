#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""提供 Windows 托盘、自启动、日志查看和后台进程管理。"""


import ctypes
import os
import subprocess
import sys
import threading
import winreg
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
from windows_settings import SettingsStore, SettingsWindow


APPLICATION_NAME = "Pico 系统监控"
AUTOSTART_NAME = "PicoHardwareMonitor"


class WindowsTrayApplication:
    """管理 Windows 托盘图标及无窗口监控工作进程。"""

    def __init__(self, worker_arguments):
        """保存工作进程参数并创建当前用户日志目录。"""
        self.worker_arguments = worker_arguments
        self.worker_process = None
        self.console_process = None
        self.stopping = threading.Event()
        self.icon = None
        self.mutex = None
        self.expected_exits = set()
        data_directory = Path(os.getenv("LOCALAPPDATA", Path.home())) / "PicoMonitor"
        data_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = data_directory / "pico-monitor.log"
        self.settings_store = SettingsStore(data_directory / "settings.json")
        self.settings_window = None

    def _acquire_single_instance(self):
        """获取系统互斥量，确保托盘程序只有一个实例。"""
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PicoHardwareMonitor")
        return ctypes.windll.kernel32.GetLastError() != 183

    def _worker_command(self):
        """构造源码模式或打包模式下的后台工作命令。"""
        configured = SettingsStore.worker_arguments(self.settings_store.load())
        if getattr(sys, "frozen", False):
            return [sys.executable, *self.worker_arguments, *configured]
        return [sys.executable, str(Path(__file__).with_name("pico_monitor.py")), *self.worker_arguments, *configured]

    def _start_worker(self):
        """无窗口启动工作进程，并异步将输出写入日志。"""
        environment = os.environ.copy()
        environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        process = subprocess.Popen(self._worker_command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=0x08000000, env=environment)
        self.worker_process = process
        threading.Thread(target=self._collect_output, args=(process,), name="日志收集", daemon=True).start()

    def _collect_output(self, process):
        """持续保存工作进程输出，并在异常退出时弹出通知。"""
        with self.log_path.open("a", encoding="utf-8", newline="") as log_file:
            for line in process.stdout:
                log_file.write(line)
                log_file.flush()
        return_code = process.wait()
        expected = process in self.expected_exits
        self.expected_exits.discard(process)
        if not expected and not self.stopping.is_set() and self.icon is not None:
            self.icon.notify(f"后台监控已退出，返回码：{return_code}", APPLICATION_NAME)

    def _show_log(self, icon=None, item=None):
        """打开 PowerShell 窗口并实时显示 UTF-8 日志。"""
        del icon, item
        if self.console_process is not None and self.console_process.poll() is None:
            return
        environment = os.environ.copy()
        environment["PICO_MONITOR_LOG"] = str(self.log_path)
        command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$Host.UI.RawUI.WindowTitle='Pico 系统监控日志';Get-Content -LiteralPath $env:PICO_MONITOR_LOG -Encoding UTF8 -Tail 200 -Wait"
        self.console_process = subprocess.Popen(["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command], env=environment, creationflags=0x00000010)

    @staticmethod
    def _autostart_command():
        """返回注册到当前用户启动项的完整命令。"""
        if getattr(sys, "frozen", False):
            return f'"{Path(sys.executable).resolve()}"'
        return f'"{sys.executable}" "{Path(__file__).with_name("pico_monitor.py")}"'

    @staticmethod
    def _is_autostart(item=None):
        """检查 Windows 当前用户自启动项是否有效。"""
        del item
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return value == WindowsTrayApplication._autostart_command()
        except OSError:
            return False

    def _toggle_autostart(self, icon, item):
        """切换 Windows 当前用户登录自启动状态。"""
        del item
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if self._is_autostart():
                winreg.DeleteValue(key, AUTOSTART_NAME)
            else:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, self._autostart_command())
        icon.update_menu()

    def _show_settings(self, icon=None, item=None):
        """在独立 UI 线程中显示设置窗口，避免阻塞托盘消息循环。"""
        del icon, item
        if self.settings_window is not None and self.settings_window.root is not None:
            self.settings_window.root.after(0, self.settings_window._focus)
            return
        self.settings_window = SettingsWindow(self.settings_store, self._apply_settings)
        threading.Thread(target=self.settings_window.show, name="设置窗口", daemon=True).start()

    def _apply_settings(self, settings):
        """停止旧工作进程，并按刚保存的设置重新启动。"""
        del settings
        if self.worker_process is not None and self.worker_process.poll() is None:
            self.expected_exits.add(self.worker_process)
            self.worker_process.terminate()
            self.worker_process.wait(timeout=5)
        if not self.stopping.is_set():
            self._start_worker()
            if self.icon is not None:
                self.icon.notify("配置已保存，后台监控已重新启动", APPLICATION_NAME)

    def _exit(self, icon, item):
        """停止工作进程、日志窗口和托盘消息循环。"""
        del item
        self.stopping.set()
        for process in (self.worker_process, self.console_process):
            if process is not None and process.poll() is None:
                process.terminate()
        icon.stop()

    @staticmethod
    def _create_image():
        """绘制无需外部图标资源的 Pico 监控托盘图标。"""
        image = Image.new("RGBA", (64, 64), (15, 23, 42, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 10, 56, 50), radius=7, fill=(14, 165, 233), outline=(224, 242, 254), width=3)
        draw.line((16, 39, 25, 29, 33, 35, 47, 20), fill="white", width=4)
        return image

    def run(self):
        """启动单实例后台监控并进入托盘消息循环。"""
        if not self._acquire_single_instance():
            return 0
        self._start_worker()
        menu = pystray.Menu(
            pystray.MenuItem("Monitor 设置", self._show_settings, default=True),
            pystray.MenuItem("打开日志", self._show_log),
            pystray.MenuItem("系统自启", self._toggle_autostart, checked=self._is_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._exit),
        )
        self.icon = pystray.Icon("pico-monitor", self._create_image(), APPLICATION_NAME, menu)
        self.icon.run()
        return 0
