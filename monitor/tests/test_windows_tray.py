"""验证 Windows 托盘配置的纯数据行为。"""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from windows_tray import (
    DEFAULT_SETTINGS,
    STYLE_NAMES,
    TraySettingsStore,
    WindowsTrayApplication,
    apply_worker_arguments,
    settings_from_arguments,
    style_label,
    style_names,
)


class WindowsTraySettingsTest(unittest.TestCase):
    def setUp(self):
        """创建测试使用的临时目录。"""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def _create_log_application(self):
        """创建仅包含日志导出状态的托盘应用实例。"""
        data_directory = Path(self.temporary_directory.name)
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.data_directory = data_directory
        application.log_path = data_directory / "pico-monitor.log"
        return application

    def test_recent_log_export_is_limited_to_one_megabyte(self):
        """确认日志导出只读取末尾一兆字节。"""
        application = self._create_log_application()
        expected = b"b" * (1024 * 1024)
        application.log_path.write_bytes(b"a" * 64 + expected)

        self.assertEqual(expected, application._read_recent_log())

    def test_recent_log_export_keeps_complete_chinese_characters(self):
        """确认日志截取位置位于中文字符中间时不会产生乱码。"""
        application = self._create_log_application()
        application.log_path.write_bytes("甲乙丙".encode("utf-8"))

        self.assertEqual("乙丙".encode("utf-8"), application._read_recent_log(7))

    @mock.patch("win.tray.subprocess.Popen")
    def test_export_log_creates_file_and_opens_directory(self, popen):
        """确认托盘导出日志后使用资源管理器选中导出文件。"""
        application = self._create_log_application()
        application.log_path.write_text("测试日志", encoding="utf-8")

        application._export_log()

        exported_files = list((application.data_directory / "exports").glob("*.log"))
        self.assertEqual(1, len(exported_files))
        self.assertEqual("测试日志", exported_files[0].read_text(encoding="utf-8"))
        popen.assert_called_once_with(
            ["explorer.exe", "/select,", str(exported_files[0])],
            creationflags=0x08000000,
        )

    @mock.patch("win.tray.threading.Thread")
    def test_settings_window_can_only_be_opened_once(self, thread_class):
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings_window_lock = threading.Lock()
        application.settings_window_open = False
        application.settings_window_restore_requested = threading.Event()
        icon = mock.Mock()

        application._show_settings(icon)
        application._show_settings(icon)

        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()
        self.assertTrue(application.settings_window_restore_requested.is_set())
        icon.notify.assert_not_called()

    def test_every_style_has_a_chinese_label(self):
        for name in STYLE_NAMES:
            self.assertNotEqual(STYLE_NAMES[name], name)
            self.assertIn(name, style_label(name))

    def test_display_settings_are_sent_without_restarting_worker(self):
        """确认显示配置通过标准输入热更新，不重启 Monitor。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings = dict(
            DEFAULT_SETTINGS,
            lcd_style="simple",
            screen_rotation=180,
            lcd_brightness=35,
            network_unit="Mbps",
        )
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        self.assertTrue(application._apply_display_settings())

        written = application.worker_process.stdin.write.call_args.args[0]
        self.assertTrue(written.startswith("DISPLAY_CONFIG:"))
        payload = json.loads(written.removeprefix("DISPLAY_CONFIG:"))
        self.assertEqual(payload["lcd_brightness"], 35)
        application.worker_process.stdin.flush.assert_called_once_with()

    def test_managed_arguments_are_replaced_without_losing_worker_flag(self):
        settings = dict(
            DEFAULT_SETTINGS,
            lcd_style="simple",
            screen_rotation=180,
            lcd_brightness=35,
        )
        result = apply_worker_arguments(
            ["--lcd-style", "default", "--screen-rotation", "0", "--worker"],
            settings,
        )
        self.assertEqual(result.count("--lcd-style"), 1)
        self.assertEqual(result[result.index("--lcd-style") + 1], "simple")
        self.assertEqual(result[result.index("--lcd-brightness") + 1], "35")
        self.assertIn("--worker", result)

    def test_first_run_imports_existing_arguments(self):
        settings = settings_from_arguments([
            "--lcd-style", "diskv4", "--interval", "1.5",
            "--qbittorrent-enabled",
        ])
        self.assertEqual(settings["lcd_style"], "diskv4")
        self.assertEqual(settings["interval"], 1.5)
        self.assertTrue(settings["qbittorrent_enabled"])

    def test_store_ignores_unknown_fields_and_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"lcd_style": "simple", "unknown": 1}), encoding="utf-8")
            settings = TraySettingsStore(path).load()
        self.assertEqual(settings["lcd_style"], "simple")
        self.assertEqual(settings["ping_target"], DEFAULT_SETTINGS["ping_target"])
        self.assertNotIn("unknown", settings)

    def test_store_persists_pico_style_catalog(self):
        """确认 Pico 清单中的中文名称和样式类型能够持久化。"""
        catalog = [
            {"name": "custom_clock", "chinese_name": "自定义时钟", "type": "custom"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            settings = dict(DEFAULT_SETTINGS, styles=catalog, lcd_style="custom_clock")
            store.save(settings)
            loaded = store.load()
        self.assertEqual(loaded["styles"], catalog)
        self.assertEqual(style_names(loaded), {"custom_clock": "自定义时钟"})
        self.assertEqual(style_label("custom_clock", loaded), "自定义时钟（custom_clock）")


if __name__ == "__main__":
    unittest.main()
