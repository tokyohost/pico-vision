"""验证 Debian 同时间戳、同长度升级时强制刷新 Python 缓存。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DebianBytecodeTests(unittest.TestCase):
    """复现旧版本缓存，并验证安装脚本采用的刷新方式。"""

    def test_force_compile_refreshes_same_size_and_timestamp(self):
        """新旧版本仅数字不同且时间戳一致时，强制编译仍应加载新版本。"""
        # CI 默认禁止写入字节码；仅为复现旧缓存的子进程启用缓存，避免改变测试入口环境。
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "build_info.py"
            source.write_text('MONITOR_VERSION = "2.4.11-build5"\n', encoding="utf-8")
            os.utime(source, (1782835200, 1782835200))
            command = [sys.executable, "-c", "import build_info; print(build_info.MONITOR_VERSION)"]
            old = subprocess.check_output(command, cwd=directory, env=environment, text=True).strip()
            self.assertEqual(old, "2.4.11-build5")
            source.write_text('MONITOR_VERSION = "2.4.12-build5"\n', encoding="utf-8")
            os.utime(source, (1782835200, 1782835200))
            stale = subprocess.check_output(command, cwd=directory, env=environment, text=True).strip()
            self.assertEqual(stale, "2.4.11-build5")
            subprocess.run(
                [sys.executable, "-m", "compileall", "-q", "-f", directory],
                env=environment, check=True,
            )
            updated = subprocess.check_output(command, cwd=directory, env=environment, text=True).strip()
            self.assertEqual(updated, "2.4.12-build5")

    def test_postinst_refreshes_cache_before_debhelper_service_actions(self):
        """安装配置阶段先更新字节码，再执行 debhelper 的服务处理。"""
        script = (Path(__file__).resolve().parents[1] / "debian" / "postinst").read_text(encoding="utf-8")
        command = "/usr/bin/python3 -m compileall -q -f /usr/lib/pico-monitor"
        self.assertIn("configure)", script)
        self.assertLess(script.index(command), script.index("#DEBHELPER#"))
