"""Windows 开机自动启动管理。"""

import logging
import subprocess
import sys
import winreg
from pathlib import Path

from .constants import APPLICATION_NAME, AUTOSTART_NAME, MONITOR_DIRECTORY


LOGGER = logging.getLogger("pico-monitor.autostart")
AUTOSTART_TASK_NAME = "OmniWatch Monitor Autostart"
RUN_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartMixin:
    """通过最高权限登录任务为托盘应用提供可靠的自动启动能力。"""

    @staticmethod
    def _autostart_command():
        """构造当前程序的 Windows 开机启动命令。"""
        if getattr(sys, "frozen", False):
            return '"{}"'.format(Path(sys.executable).resolve())
        return '"{}" "{}"'.format(
            Path(sys.executable).resolve(),
            (MONITOR_DIRECTORY / "pico_monitor.py").resolve(),
        )

    @staticmethod
    def _run_task_scheduler(*arguments):
        """以隐藏窗口方式调用任务计划程序并返回执行结果。"""
        return subprocess.run(
            ["schtasks.exe", *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )

    @classmethod
    def _task_exists(cls):
        """检查当前用户的 Monitor 登录启动任务是否存在。"""
        result = cls._run_task_scheduler(
            "/Query",
            "/TN",
            AUTOSTART_TASK_NAME,
        )
        return result.returncode == 0

    @staticmethod
    def _legacy_autostart_exists():
        """检查旧版本写入的当前用户 Run 注册表项是否存在。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REGISTRY_PATH) as key:
                winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
        except OSError:
            return False

    @staticmethod
    def _remove_legacy_autostart():
        """删除无法可靠启动提权程序的旧版 Run 注册表项。"""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_REGISTRY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, AUTOSTART_NAME)
        except OSError:
            return

    @classmethod
    def _create_autostart_task(cls):
        """创建登录时以最高权限启动 Monitor 的计划任务。"""
        result = cls._run_task_scheduler(
            "/Create",
            "/TN",
            AUTOSTART_TASK_NAME,
            "/TR",
            cls._autostart_command(),
            "/SC",
            "ONLOGON",
            "/RL",
            "HIGHEST",
            "/IT",
            "/F",
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "未知错误").strip()
            raise RuntimeError("创建开机启动任务失败：{}".format(detail))

    @classmethod
    def _delete_autostart_task(cls):
        """删除 Monitor 的登录启动计划任务。"""
        result = cls._run_task_scheduler(
            "/Delete",
            "/TN",
            AUTOSTART_TASK_NAME,
            "/F",
        )
        if result.returncode != 0 and cls._task_exists():
            detail = (result.stderr or result.stdout or "未知错误").strip()
            raise RuntimeError("删除开机启动任务失败：{}".format(detail))

    @classmethod
    def _migrate_legacy_autostart(cls):
        """把旧版 Run 注册表配置迁移为可启动提权程序的计划任务。"""
        if not cls._legacy_autostart_exists():
            return False
        if not cls._task_exists():
            cls._create_autostart_task()
        cls._remove_legacy_autostart()
        return True

    @classmethod
    def _is_autostart(cls, item=None):
        """检查当前程序是否已注册为开机自动启动。"""
        del item
        return cls._task_exists()

    def _toggle_autostart(self, icon, item):
        """切换开机自动启动任务状态并向用户报告操作结果。"""
        del item
        try:
            if self._is_autostart():
                self._delete_autostart_task()
                self._remove_legacy_autostart()
                message = "开机自动启动已关闭"
            else:
                self._create_autostart_task()
                self._remove_legacy_autostart()
                message = "开机自动启动已开启"
            icon.update_menu()
            icon.notify(message, APPLICATION_NAME)
        except (OSError, RuntimeError) as error:
            LOGGER.exception("切换开机自动启动失败：%s", error)
            icon.notify(str(error), APPLICATION_NAME)
