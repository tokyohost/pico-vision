"""Windows 开机自动启动管理。"""

import sys
import winreg
from pathlib import Path

from .constants import AUTOSTART_NAME, MONITOR_DIRECTORY


class AutostartMixin:
    """为托盘应用提供独立的业务能力。"""

    @staticmethod
    def _autostart_command():
        """构造当前程序的 Windows 开机启动命令。"""
        if getattr(sys, "frozen", False):
            return '"{}"'.format(Path(sys.executable).resolve())
        return '"{}" "{}"'.format(sys.executable, MONITOR_DIRECTORY / "pico_monitor.py")

    @staticmethod
    def _is_autostart(item=None):
        """检查当前程序是否已注册为开机自动启动。"""
        del item
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return value == AutostartMixin._autostart_command()
        except OSError:
            return False

    def _toggle_autostart(self, icon, item):
        """切换开机自动启动状态并刷新托盘菜单。"""
        del item
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if self._is_autostart():
                winreg.DeleteValue(key, AUTOSTART_NAME)
            else:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, self._autostart_command())
        icon.update_menu()
