"""验证 Windows 托盘配置的纯数据行为。"""

import json
import logging
import queue
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
from monitor_core.tray_commands import _dispatch_tray_command
from win.tray import APPLICATION_NAME
from win.worker_controller import MAXIMUM_LOG_SIZE, WorkerControllerMixin
from style_validator import ValidatedStyle


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
        application.settings = dict(
            DEFAULT_SETTINGS,
            lcd_brightness=66,
            qbittorrent_password="不能导出的密码",
        )
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

    def test_runtime_log_keeps_only_latest_fifteen_megabytes(self):
        """确认运行日志超过十五兆字节后仅保留最新内容。"""
        log_path = Path(self.temporary_directory.name) / "pico-monitor.log"
        latest_content = b"b" * MAXIMUM_LOG_SIZE
        log_path.write_bytes(b"old" + latest_content)

        with log_path.open("r+b") as log_file:
            log_file.seek(0, 2)
            WorkerControllerMixin._truncate_log_file(log_file)

        self.assertEqual(MAXIMUM_LOG_SIZE, log_path.stat().st_size)
        self.assertEqual(latest_content, log_path.read_bytes())

    def test_runtime_log_truncation_keeps_complete_chinese_characters(self):
        """确认运行日志截断后不会留下不完整的中文 UTF-8 字符。"""
        log_path = Path(self.temporary_directory.name) / "pico-monitor.log"
        log_path.write_bytes("甲乙丙".encode("utf-8"))

        with log_path.open("r+b") as log_file:
            log_file.seek(0, 2)
            WorkerControllerMixin._truncate_log_file(log_file, 7)

        self.assertEqual("乙丙", log_path.read_text(encoding="utf-8"))

    def test_activate_custom_data_plugin_writes_worker_command(self):
        """确认自定义数据实时运行命令会写入后台监控管道。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        result = application._activate_custom_data_plugin("weather")

        self.assertTrue(result)
        command = application.worker_process.stdin.write.call_args.args[0]
        self.assertEqual(json.loads(command.removeprefix("CUSTOM_DATA_ACTIVATE:")), {"name": "weather"})
        application.worker_process.stdin.flush.assert_called_once_with()

    def test_tray_command_dispatch_activates_custom_data_plugin(self):
        """确认后台进程能解析自定义数据实时运行命令。"""
        service = mock.Mock()

        should_stop = _dispatch_tray_command(service, 'CUSTOM_DATA_ACTIVATE:{"name":"weather"}')

        self.assertFalse(should_stop)
        service.activate_custom_data_plugin.assert_called_once_with("weather")

    def test_worker_result_parser_ignores_trailing_log_text(self):
        """确认后台结构化结果后粘连普通日志时仍按第一段 JSON 解析。"""
        line = (
            'CUSTOM_STYLE_UPLOAD_RESULT:{"status":"ok","data":{"filename":"style_weather_panel.py"}}'
            "2026-07-10 11:08:20,233 [INFO] STYLE_CATALOG_UPDATED：已同步 15 个 Pico 样式"
        )

        result = WorkerControllerMixin._parse_worker_result(
            line, "CUSTOM_STYLE_UPLOAD_RESULT:", "设备返回了无效响应",
        )

        self.assertEqual("ok", result["status"])
        self.assertEqual("style_weather_panel.py", result["data"]["filename"])

    def test_worker_result_parser_reports_invalid_json(self):
        """确认后台结构化结果无法解析时返回统一的中文错误。"""
        result = WorkerControllerMixin._parse_worker_result(
            "CUSTOM_STYLE_UPLOAD_RESULT:not-json",
            "CUSTOM_STYLE_UPLOAD_RESULT:",
            "设备返回了无效响应",
        )

        self.assertEqual({"status": "error", "message": "设备返回了无效响应"}, result)

    def test_error_log_is_created_only_for_error_level_messages(self):
        """确认错误消息会自动写入以 error.log 结尾的独立日志文件。"""
        application = self._create_log_application()
        root_logger = logging.getLogger()
        original_handlers = set(root_logger.handlers)
        error_log_path = application._configure_error_logging()
        error_handler = next(
            handler
            for handler in root_logger.handlers
            if handler not in original_handlers
        )
        logger = logging.getLogger("pico-monitor.test-error-log")

        def remove_error_handler():
            """关闭测试添加的错误处理器，避免 Windows 持有临时文件。"""
            root_logger.removeHandler(error_handler)
            error_handler.close()

        self.addCleanup(remove_error_handler)

        logger.warning("普通警告")
        logger.error("测试错误")
        for handler in logging.getLogger().handlers:
            handler.flush()

        self.assertTrue(error_log_path.name.endswith("error.log"))
        content = error_log_path.read_text(encoding="utf-8")
        self.assertIn("测试错误", content)
        self.assertNotIn("普通警告", content)

    @mock.patch("win.tray.WindowsTrayApplication._show_copyable_error_dialog")
    @mock.patch("win.tray.WindowsTrayApplication._configure_tk_runtime")
    def test_unhandled_crash_is_logged_and_shown_in_copyable_dialog(
        self,
        configure_tk_runtime,
        show_dialog,
    ):
        """确认未捕获异常会写入完整堆栈并弹出可复制窗口。"""
        del configure_tk_runtime
        application = self._create_log_application()
        application.crash_dialog_lock = threading.Lock()

        try:
            raise RuntimeError("测试崩溃")
        except RuntimeError as error:
            exception_type, exception, traceback_object = (
                type(error), error, error.__traceback__
            )
            application._report_unhandled_crash(
                exception_type,
                exception,
                traceback_object,
                "测试线程",
            )

        crash_files = list((application.data_directory / "crash").glob("*.log"))
        self.assertEqual(1, len(crash_files))
        crash_text = crash_files[0].read_text(encoding="utf-8")
        self.assertIn("测试线程", crash_text)
        self.assertIn("RuntimeError: 测试崩溃", crash_text)
        self.assertIn("test_unhandled_crash_is_logged", crash_text)
        show_dialog.assert_called_once()
        self.assertIn("RuntimeError: 测试崩溃", show_dialog.call_args.kwargs["detail"])

    @mock.patch("win.tray.WindowsTrayApplication._report_unhandled_crash")
    @mock.patch(
        "win.tray.WindowsTrayApplication.__init__",
        side_effect=RuntimeError("初始化失败"),
    )
    def test_startup_crash_uses_emergency_crash_reporter(
        self,
        initialize,
        report_crash,
    ):
        """确认托盘构造阶段失败时仍会显示崩溃报告。"""
        del initialize

        result = WindowsTrayApplication.start(["--worker"])

        self.assertEqual(1, result)
        report_crash.assert_called_once()
        self.assertIs(RuntimeError, report_crash.call_args.args[0])
        self.assertEqual("初始化失败", str(report_crash.call_args.args[1]))
        self.assertEqual("托盘启动线程", report_crash.call_args.args[3])

    @mock.patch("win.tray.subprocess.Popen")
    def test_export_log_creates_file_and_opens_directory(self, popen):
        """确认托盘导出日志后使用资源管理器选中导出文件。"""
        application = self._create_log_application()
        application.log_path.write_text("测试日志", encoding="utf-8")

        application._export_log()

        exported_files = list((application.data_directory / "exports").glob("*.log"))
        self.assertEqual(1, len(exported_files))
        exported_text = exported_files[0].read_text(encoding="utf-8")
        self.assertTrue(exported_text.startswith("===== OmniWatch 配置信息 ====="))
        self.assertIn('"lcd_brightness": 66', exported_text)
        self.assertIn('"qbittorrent_password": "******（已配置）"', exported_text)
        self.assertNotIn("不能导出的密码", exported_text)
        self.assertTrue(exported_text.endswith("===== 运行日志 =====\n测试日志"))
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
    def test_log_window_uses_single_internal_window(self, thread_class):
        """确认日志功能只创建一个应用内窗口而不启动外部控制台。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.log_window_lock = threading.Lock()
        application.log_window_open = False

        application._show_log()
        application._show_log()

        thread_class.assert_called_once()
        self.assertEqual("日志窗口", thread_class.call_args.kwargs["name"])
        thread_class.return_value.start.assert_called_once_with()
        self.assertTrue(application.log_window_open)

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

    @mock.patch("win.ui.about_window.subprocess.Popen")
    def test_about_window_can_open_log_directory(self, popen):
        """确认关于应用窗口可以使用资源管理器打开日志目录。"""
        application = self._create_log_application()

        self.assertTrue(application._open_log_directory())

        popen.assert_called_once_with(
            ["explorer.exe", str(application.data_directory)],
            creationflags=0x08000000,
        )

    @mock.patch("PIL.ImageTk.PhotoImage")
    @mock.patch("PIL.Image.open")
    @mock.patch("win.tray.WindowsTrayApplication._set_tk_window_icon")
    @mock.patch("win.tray.WindowsTrayApplication._center_tk_window")
    @mock.patch("tkinter.Button")
    @mock.patch("tkinter.Label")
    @mock.patch("tkinter.Frame")
    @mock.patch("tkinter.Tk")
    def test_about_qr_image_belongs_to_current_window(
        self,
        tk_class,
        frame_class,
        label_class,
        button_class,
        center_window,
        set_window_icon,
        image_open,
        photo_image,
    ):
        """确认二维码绑定关于窗口自身的 Tcl 解释器，避免跨线程打开失败。"""
        del frame_class, label_class, button_class, center_window, set_window_icon
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        root = tk_class.return_value
        resized_image = image_open.return_value.__enter__.return_value.convert.return_value.resize.return_value

        application._run_about_window()

        photo_image.assert_called_once_with(resized_image, master=root)
        root.mainloop.assert_called_once_with()

    @mock.patch("win.tray.threading.Thread")
    def test_device_probe_window_can_only_be_opened_once(self, thread_class):
        """确认设备探测窗口不能被重复创建。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.device_probe_window_lock = threading.Lock()
        application.device_probe_window_open = False

        application._show_device_probe()
        application._show_device_probe()

        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once_with()
        self.assertTrue(application.device_probe_window_open)

    def test_device_probe_command_replaces_worker_mode_with_information_mode(self):
        """确认设备探测命令停用常驻模式并启用单次信息查询。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application._worker_command = mock.Mock(
            return_value=["pico-monitor.exe", "--worker", "--port", "COM9"]
        )

        command = application._device_probe_command()

        self.assertNotIn("--worker", command)
        self.assertEqual("--pico-info", command[-1])
        self.assertEqual("COM9", command[-2])

    def test_device_connection_snapshot_is_saved_and_copied(self):
        """确认设备连接状态可供新打开的设备管理窗口安全读取。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.device_connection_lock = threading.Lock()
        application.current_device_connection = {"connected": False}
        application.device_connection_messages = queue.Queue()
        connection = {"connected": True, "board_model": "rp2040"}

        application._update_device_connection(connection)
        snapshot = application._get_device_connection()
        snapshot["connected"] = False

        self.assertTrue(application._get_device_connection()["connected"])
        self.assertEqual(connection, application.device_connection_messages.get_nowait())

    @mock.patch("style_validator.StyleFileValidator.validate")
    def test_custom_style_upload_rejects_existing_filename(self, validate):
        """确认 customStyles 已存在同名文件时不会向工作进程发送上传请求。"""
        validate.return_value = ValidatedStyle(
            name="clock",
            chinese_name="时钟",
            filename="style_clock.py",
            source=b"source",
        )
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()

        with self.assertRaisesRegex(FileExistsError, "已存在样式名"):
            application.request_custom_style_upload("style_clock.py", {"clock"})

        application.worker_process.stdin.write.assert_not_called()

    @mock.patch("style_validator.StyleFileValidator.validate")
    def test_custom_style_upload_sends_validated_source(self, validate):
        """确认通过校验的样式源码会封装为工作进程上传指令。"""
        validate.return_value = ValidatedStyle(
            name="clock",
            chinese_name="时钟",
            filename="style_clock.py",
            source=b"source",
        )
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        result = application.request_custom_style_upload("style_clock.py", set())

        command = application.worker_process.stdin.write.call_args.args[0]
        payload = json.loads(command.removeprefix("CUSTOM_STYLE_UPLOAD:").strip())
        self.assertEqual("clock", result.name)
        self.assertEqual("style_clock.py", payload["filename"])
        self.assertEqual("c291cmNl", payload["content"])
        self.assertFalse(payload["overwrite"])
        application.worker_process.stdin.flush.assert_called_once_with()

    @mock.patch("style_validator.StyleFileValidator.validate")
    def test_custom_style_upload_allows_confirmed_overwrite(self, validate):
        """确认用户同意覆盖后会向工作进程发送覆盖标志。"""
        validate.return_value = ValidatedStyle(
            name="clock", chinese_name="时钟",
            filename="style_clock.py", source=b"new",
        )
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        application.request_custom_style_upload(
            "style_clock.py", {"clock"}, overwrite=True,
        )

        command = application.worker_process.stdin.write.call_args.args[0]
        payload = json.loads(command.removeprefix("CUSTOM_STYLE_UPLOAD:").strip())
        self.assertTrue(payload["overwrite"])

    def test_custom_style_delete_sends_style_identity(self):
        """确认删除请求把样式名和文件名发送给工作进程。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        application.request_custom_style_delete("clock", "style_clock.py")

        command = application.worker_process.stdin.write.call_args.args[0]
        payload = json.loads(command.removeprefix("CUSTOM_STYLE_DELETE:").strip())
        self.assertEqual(payload, {
            "style_name": "clock",
            "filename": "style_clock.py",
        })
        application.worker_process.stdin.flush.assert_called_once_with()

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

    def test_stop_worker_requests_graceful_exit_before_termination(self):
        """确认托盘退出先通知工作进程释放子进程与原生资源。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        process = mock.Mock()
        process.poll.return_value = None
        application.worker_process = process

        application._stop_worker()

        process.stdin.write.assert_called_once_with("EXIT\n")
        process.stdin.flush.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        process.stdin.close.assert_called_once_with()
        process.stdout.close.assert_called_once_with()
        self.assertIsNone(application.worker_process)

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

    def test_toggle_dev_mode_persists_and_hot_updates_worker(self):
        """确认托盘切换开发模式后保存配置并热更新现有进程。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.settings = dict(DEFAULT_SETTINGS, dev=False)
        application.settings_store = mock.Mock()
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None
        icon = mock.Mock()

        application._toggle_dev_mode(icon, None)

        self.assertTrue(application.settings["dev"])
        application.settings_store.save.assert_called_once_with(application.settings)
        command = application.worker_process.stdin.write.call_args.args[0]
        self.assertEqual(json.loads(command.removeprefix("DEV_CONFIG:")), {"enabled": True})
        application.worker_process.stdin.flush.assert_called_once_with()
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

    @mock.patch("win.tray.WindowsReleaseUpdater")
    def test_update_uses_fixed_repository_address(self, updater_class):
        """确认版本检查始终使用固定发布仓库地址。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.update_lock = threading.Lock()
        application.update_lock.acquire()
        application._perform_update = mock.Mock()
        updater_class.return_value.default_update_url.return_value = (
            "https://api.github.com/repos/tokyohost/omniwatch-doc/releases/latest"
        )
        icon = mock.Mock()

        application._prompt_and_perform_update(icon)

        application._perform_update.assert_called_once_with(
            icon,
            "https://api.github.com/repos/tokyohost/omniwatch-doc/releases/latest",
        )

    @mock.patch("tkinter.messagebox.askyesno", return_value=False)
    @mock.patch("tkinter.Tk")
    def test_application_update_requires_user_confirmation(self, tk_class, ask_yes_no):
        """确认托盘检查到新版本后会展示更新说明并等待用户确认。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application._configure_tk_runtime = mock.Mock()
        application._set_tk_window_icon = mock.Mock()

        confirmed = application._confirm_application_update("2.0.0", "修复设备连接问题")

        self.assertFalse(confirmed)
        self.assertIn("修复设备连接问题", ask_yes_no.call_args.args[1])
        tk_class.return_value.destroy.assert_called_once_with()

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
        """确认设备自定义样式与完整内置样式清单合并持久化。"""
        catalog = [
            {"name": "custom_clock", "chinese_name": "自定义时钟", "type": "custom"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            settings = dict(DEFAULT_SETTINGS, styles=catalog, lcd_style="custom_clock")
            store.save(settings)
            loaded = store.load()
        self.assertEqual(loaded["styles"][-1], catalog[0])
        self.assertEqual(
            style_names(loaded),
            dict(STYLE_NAMES, custom_clock="自定义时钟"),
        )
        self.assertEqual(style_label("custom_clock", loaded), "自定义时钟（custom_clock）")

    def test_store_rejects_custom_style_conflicting_with_builtin_style(self):
        """确认自定义样式标识与内置样式冲突时保留内置样式。"""
        catalog = [
            {"name": "simple", "chinese_name": "冲突样式", "type": "custom"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            store.save(dict(DEFAULT_SETTINGS, styles=catalog, lcd_style="simple"))
            loaded = store.load()

        self.assertEqual(style_names(loaded)["simple"], STYLE_NAMES["simple"])
        self.assertEqual(
            sum(item["name"] == "simple" for item in loaded["styles"]),
            1,
        )

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
        self.assertEqual(
            dict(STYLE_NAMES, custom_clock="自定义时钟"),
            style_names(application.settings),
        )
        self.assertTrue(application.settings["dev"])


if __name__ == "__main__":
    unittest.main()
