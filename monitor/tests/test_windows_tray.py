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
from win.tray import APPLICATION_NAME


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

    @mock.patch("win.tray.threading.Thread")
    def test_about_window_can_only_be_opened_once(self, thread_class):
        """确认关于应用窗口不能被重复创建。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.about_window_lock = threading.Lock()
        application.about_window_open = False

        application._show_about()
        application._show_about()

        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()
        self.assertTrue(application.about_window_open)

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

    def test_dev_mode_is_applied_to_worker_arguments(self):
        """确认托盘开发模式配置会替换已有参数并传递给工作进程。"""
        enabled = apply_worker_arguments(["--no-dev", "--worker"], dict(DEFAULT_SETTINGS, dev=True))
        disabled = apply_worker_arguments(["--dev", "--worker"], dict(DEFAULT_SETTINGS, dev=False))

        self.assertIn("--dev", enabled)
        self.assertNotIn("--no-dev", enabled)
        self.assertNotIn("--dev", disabled)
        self.assertIn("--worker", disabled)

    def test_toggle_dev_mode_persists_and_restarts_worker(self):
        """确认托盘切换开发模式后保存配置并重启后台进程。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings = dict(DEFAULT_SETTINGS, dev=False)
        application.settings_store = mock.Mock()
        application._restart_worker = mock.Mock()
        icon = mock.Mock()

        application._toggle_dev_mode(icon, None)

        self.assertTrue(application.settings["dev"])
        application.settings_store.save.assert_called_once_with(application.settings)
        application._restart_worker.assert_called_once_with()
        icon.update_menu.assert_called_once_with()
        icon.notify.assert_called_once_with("开发模式已开启", APPLICATION_NAME)

    def test_windows_exit_stops_monitor_without_rebooting_pico(self):
        """确认退出 Windows Monitor 时不会向 Pico 发送重启指令。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.stopping = threading.Event()
        application.worker_process = mock.Mock()
        application.console_process = None
        application._stop_worker = mock.Mock()
        icon = mock.Mock()

        application._exit(icon, None)

        self.assertTrue(application.stopping.is_set())
        application._stop_worker.assert_called_once_with()
        application.worker_process.stdin.write.assert_not_called()
        icon.stop.assert_called_once_with()

    @mock.patch("win.tray.threading.Thread")
    def test_check_update_starts_only_one_background_task(self, thread_class):
        """确认连续点击检查更新时只启动一个后台任务。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.update_lock = threading.Lock()
        application.settings = dict(DEFAULT_SETTINGS)
        application.settings_store = mock.Mock()
        application._ask_update_url = mock.Mock(return_value="https://updates.example/latest")
        icon = mock.Mock()

        application._check_for_updates(icon)
        application._check_for_updates(icon)

        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()
        icon.notify.assert_called_once_with("更新任务正在执行，请稍候", APPLICATION_NAME)

    def test_cancel_update_dialog_releases_task_lock(self):
        """确认关闭更新地址窗口后可以再次执行检查。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.update_lock = threading.Lock()
        application.update_lock.acquire()
        application._ask_update_url = mock.Mock(return_value=None)
        icon = mock.Mock()

        application._prompt_and_perform_update(icon)

        self.assertTrue(application.update_lock.acquire(blocking=False))

    def test_confirm_update_dialog_passes_address_to_updater(self):
        """确认地址窗口确定后保存配置并进入更新流程。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.update_lock = threading.Lock()
        application.update_lock.acquire()
        application.settings = dict(DEFAULT_SETTINGS)
        application.settings_store = mock.Mock()
        application._ask_update_url = mock.Mock(return_value="https://updates.example/latest")
        application._perform_update = mock.Mock()
        icon = mock.Mock()

        application._prompt_and_perform_update(icon)

        application.settings_store.save.assert_called_once_with(application.settings)
        application._perform_update.assert_called_once_with(icon, "https://updates.example/latest")

    def test_empty_update_address_uses_default(self):
        """确认更新地址留空时使用正式构建内置的默认地址。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings = dict(DEFAULT_SETTINGS, update_url="")
        updater = mock.Mock()
        updater.default_update_url.return_value = "https://updates.example/default"

        application._show_update_url_input = mock.Mock(return_value="")
        with mock.patch("win.tray.WindowsReleaseUpdater", return_value=updater), mock.patch(
            "tkinter.Tk"
        ) as tk_class:
            self.assertEqual(
                "https://updates.example/default",
                application._ask_update_url(),
            )
        tk_class.return_value.destroy.assert_called_once_with()

    def test_first_run_imports_existing_arguments(self):
        settings = settings_from_arguments([
            "--lcd-style", "diskv4", "--interval", "1.5",
            "--qbittorrent-enabled",
        ])
        self.assertEqual(settings["lcd_style"], "diskv4")
        self.assertEqual(settings["interval"], 1.5)
        self.assertTrue(settings["qbittorrent_enabled"])

    def test_first_run_imports_dev_argument(self):
        """确认首次运行时从已有启动参数导入开发模式。"""
        self.assertTrue(settings_from_arguments(["--dev"])["dev"])

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

    def test_tray_reloads_pico_style_catalog_without_replacing_other_settings(self):
        """确认托盘刷新 Pico 样式时同步选中项且不覆盖其他内存配置。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings = dict(DEFAULT_SETTINGS, dev=True, lcd_style="simple")
        application.settings_store = mock.Mock()
        application.settings_store.load.return_value = dict(
            DEFAULT_SETTINGS,
            styles=[{"name": "custom_clock", "chinese_name": "自定义时钟", "type": "custom"}],
            lcd_style="custom_clock",
            dev=False,
        )

        application._reload_style_catalog()

        self.assertEqual("custom_clock", application.settings["lcd_style"])
        self.assertEqual({"custom_clock": "自定义时钟"}, style_names(application.settings))
        self.assertTrue(application.settings["dev"])


if __name__ == "__main__":
    unittest.main()
