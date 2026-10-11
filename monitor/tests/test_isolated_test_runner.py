"""验证跨平台隔离测试入口不会漏报失败或在 Mac 伪造 Windows 原生 API。"""

import io
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from tools import run_isolated_tests as runner


class IsolatedTestRunnerTest(unittest.TestCase):
    """覆盖原生平台筛选、冷启动命令和失败传播。"""

    def run_with_files(self, names, platform, return_code=0, side_effect=None):
        """替换测试文件清单与子进程，避免本入口测试递归启动完整回归。"""
        with mock.patch.object(Path, "glob", return_value=[Path(name) for name in names]), \
             mock.patch.object(runner.sys, "platform", platform), \
             mock.patch.object(runner.subprocess, "run", return_value=mock.Mock(returncode=return_code),
                               side_effect=side_effect) as execute, \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            result = runner.main([])
        return result, execute

    def test_macos_only_excludes_windows_native_modules(self):
        """Mac 仅排除注册表依赖文件，USB 与 macOS 全部用例仍执行。"""
        result, execute = self.run_with_files(
            ["test_windows_autostart.py", "test_windows_power_resume.py", "test_usb_cdc_framework.py", "test_mac_os_desktop.py"],
            "darwin",
        )
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_count, 2)
        for call in execute.call_args_list:
            self.assertIn("unittest", call.args[0])
            self.assertEqual(call.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(call.kwargs["cwd"], runner.MONITOR_ROOT)

    def test_windows_executes_native_modules(self):
        """Windows 原生回归必须执行注册表和电源恢复文件。"""
        result, execute = self.run_with_files(["test_windows_autostart.py", "test_windows_power_resume.py"], "win32")
        self.assertEqual(result, 0)
        self.assertEqual(execute.call_count, 2)

    def test_failure_is_reported_while_remaining_files_execute(self):
        """任一失败使入口失败，但不跳过后续文件以隐藏其他缺陷。"""
        result, execute = self.run_with_files(["test_first.py", "test_second.py"], "darwin", return_code=1)
        self.assertEqual(result, 1)
        self.assertEqual(execute.call_count, 2)

    def test_timeout_is_failure(self):
        """子进程超时不得视为通过。"""
        result, _ = self.run_with_files(["test_slow.py"], "darwin",
                                        side_effect=subprocess.TimeoutExpired("unittest", 180))
        self.assertEqual(result, 1)

    def test_empty_file_selection_is_error(self):
        """没有发现测试文件时拒绝产生假成功。"""
        with self.assertRaisesRegex(RuntimeError, "没有匹配的测试文件"):
            self.run_with_files([], "darwin")


if __name__ == "__main__":
    unittest.main()
