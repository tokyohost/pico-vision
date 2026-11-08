"""验证 DEB 配置迁移、重复升级和 systemd 写入边界。"""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from monitor_core.install_config import migrate_config


class InstallConfigTests(unittest.TestCase):
    """保护用户原配置，确保升级不覆盖 HTTP 已保存的内容。"""

    def test_migration_preserves_original_bytes_and_is_repeatable(self):
        """旧配置完整迁移并保留备份，后续升级不覆盖新配置。"""
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "pico-monitor.conf"
            target = Path(directory) / "pico-monitor" / "config.yaml"
            original = b"disk:\n  allow_wakeup: false\n  smart_interval_minutes: 45\n"
            legacy.write_bytes(original)
            self.assertTrue(migrate_config(legacy, target))
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(legacy.read_bytes(), original)
            target.write_bytes(b"http: {port: 1234}\n")
            self.assertFalse(migrate_config(legacy, target))
            self.assertEqual(target.read_bytes(), b"http: {port: 1234}\n")

    def test_manual_fix_is_preserved_without_legacy_file(self):
        """已有手动修复配置时不依赖旧路径，也不覆盖现有文件。"""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text("{}", encoding="utf-8")
            self.assertFalse(migrate_config(Path(directory) / "missing", target))

    def test_failed_migration_does_not_leave_partial_configuration(self):
        """复制失败保留旧配置并清理临时文件，允许下次安装重试。"""
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / "old.conf"
            target = Path(directory) / "settings" / "config.yaml"
            legacy.write_text("{}", encoding="utf-8")
            with mock.patch("monitor_core.install_config.shutil.copyfileobj", side_effect=OSError("写入失败")):
                with self.assertRaises(OSError):
                    migrate_config(legacy, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.iterdir()), [])
            self.assertEqual(legacy.read_text(), "{}")

    def test_service_and_installation_order_match_writable_directory(self):
        """服务只开放专用目录，迁移和缓存刷新均在服务启动前完成。"""
        root = Path(__file__).resolve().parents[1] / "debian"
        service = (root / "pico-monitor.service").read_text(encoding="utf-8")
        postinst = (root / "postinst").read_text(encoding="utf-8")
        self.assertIn("--config /etc/pico-monitor/config.yaml", service)
        self.assertIn("ReadWritePaths=/etc/pico-monitor\n", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertLess(postinst.index("install_config.py"), postinst.index("compileall"))
        self.assertLess(postinst.index("compileall"), postinst.index("#DEBHELPER#"))
