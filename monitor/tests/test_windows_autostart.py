"""验证 Windows Monitor 开机自动启动任务管理。"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MONITOR_ROOT = Path(__file__).resolve().parents[1]
TEST_PACKAGE_NAME = "_windows_autostart_test_package"
TEST_PACKAGE = types.ModuleType(TEST_PACKAGE_NAME)
TEST_PACKAGE.__path__ = [str(MONITOR_ROOT / "win")]
sys.modules[TEST_PACKAGE_NAME] = TEST_PACKAGE
MODULE_SPEC = importlib.util.spec_from_file_location(
    TEST_PACKAGE_NAME + ".autostart",
    MONITOR_ROOT / "win" / "autostart.py",
)
AUTOSTART_MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = AUTOSTART_MODULE
MODULE_SPEC.loader.exec_module(AUTOSTART_MODULE)
AUTOSTART_TASK_NAME = AUTOSTART_MODULE.AUTOSTART_TASK_NAME
AutostartMixin = AUTOSTART_MODULE.AutostartMixin


class WindowsAutostartTest(unittest.TestCase):
    """确认提权应用使用最高权限登录任务并迁移旧配置。"""

    def test_create_task_uses_logon_trigger_and_highest_privilege(self):
        """创建任务时应配置登录触发器和最高运行权限。"""
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with mock.patch.object(
            AutostartMixin,
            "_run_task_scheduler",
            return_value=completed,
        ) as scheduler, mock.patch.object(
            AutostartMixin,
            "_autostart_command",
            return_value='"C:\\Program Files\\OmniWatch Monitor\\pico-monitor.exe"',
        ):
            AutostartMixin._create_autostart_task()

        scheduler.assert_called_once_with(
            "/Create",
            "/TN",
            AUTOSTART_TASK_NAME,
            "/TR",
            '"C:\\Program Files\\OmniWatch Monitor\\pico-monitor.exe"',
            "/SC",
            "ONLOGON",
            "/RL",
            "HIGHEST",
            "/IT",
            "/F",
        )

    def test_migrate_legacy_registry_entry_to_scheduled_task(self):
        """检测到旧 Run 注册表项时应创建新任务并删除旧配置。"""
        with mock.patch.object(
            AutostartMixin,
            "_legacy_autostart_exists",
            return_value=True,
        ), mock.patch.object(
            AutostartMixin,
            "_task_exists",
            return_value=False,
        ), mock.patch.object(
            AutostartMixin,
            "_create_autostart_task",
        ) as create_task, mock.patch.object(
            AutostartMixin,
            "_remove_legacy_autostart",
        ) as remove_legacy:
            migrated = AutostartMixin._migrate_legacy_autostart()

        self.assertTrue(migrated)
        create_task.assert_called_once_with()
        remove_legacy.assert_called_once_with()

    def test_failed_migration_keeps_legacy_registry_entry(self):
        """新任务创建失败时不应删除仍可供诊断的旧配置。"""
        with mock.patch.object(
            AutostartMixin,
            "_legacy_autostart_exists",
            return_value=True,
        ), mock.patch.object(
            AutostartMixin,
            "_task_exists",
            return_value=False,
        ), mock.patch.object(
            AutostartMixin,
            "_create_autostart_task",
            side_effect=RuntimeError("任务创建失败"),
        ), mock.patch.object(
            AutostartMixin,
            "_remove_legacy_autostart",
        ) as remove_legacy:
            with self.assertRaisesRegex(RuntimeError, "任务创建失败"):
                AutostartMixin._migrate_legacy_autostart()

        remove_legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
