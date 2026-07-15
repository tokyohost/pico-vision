"""验证 Windows 托盘配置的纯数据行为。"""

import io
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
from win.ui.device_window import parse_device_information_line
from win.ui.wifi_window import merge_wifi_networks
from style_validator import ValidatedStyle


class WindowsTraySettingsTest(unittest.TestCase):
    """验证 Windows 托盘配置、窗口与后台进程控制行为。"""

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
        application.log_file_lock = threading.Lock()
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

    def test_clear_log_empties_runtime_log_file(self):
        """确认清空日志会保留日志文件并删除其中全部内容。"""
        application = self._create_log_application()
        application.log_path.write_text("待清空的系统监控日志", encoding="utf-8")

        application._clear_log()

        self.assertTrue(application.log_path.exists())
        self.assertEqual(b"", application.log_path.read_bytes())

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

    def test_tray_command_dispatch_requests_wifi_scan(self):
        """确认后台进程能解析 Wi-Fi 扫描命令。"""
        service = mock.Mock()

        should_stop = _dispatch_tray_command(service, "WIFI_LIST")

        self.assertFalse(should_stop)
        service.request_wifi_list.assert_called_once_with()

    def test_tray_command_dispatch_requests_wifi_connection(self):
        """确认 Wi-Fi 名称和密钥会作为结构化参数交给监控服务。"""
        service = mock.Mock()

        should_stop = _dispatch_tray_command(
            service,
            'WIFI_CONNECT:{"ssid":"测试网络","password":"测试密钥"}',
        )

        self.assertFalse(should_stop)
        service.request_wifi_connect.assert_called_once_with({
            "ssid": "测试网络",
            "password": "测试密钥",
        })

    def test_tray_command_dispatch_requests_forgetting_saved_wifi(self):
        """确认后台进程能解析忘记已保存 Wi-Fi 的命令。"""
        service = mock.Mock()

        should_stop = _dispatch_tray_command(
            service,
            'WIFI_FORGET:{"ssid":"已保存网络"}',
        )

        self.assertFalse(should_stop)
        service.request_wifi_forget.assert_called_once_with({"ssid": "已保存网络"})

    def test_wifi_list_keeps_saved_network_outside_scan_range(self):
        """确认未被本次扫描发现的已保存网络仍会显示。"""
        networks = merge_wifi_networks(
            [{"ssid": "附近网络", "rssi": -40, "security": 3}],
            {"ssid": "已保存网络", "connected": False},
        )

        self.assertEqual(["已保存网络", "附近网络"], [item["ssid"] for item in networks])
        self.assertTrue(networks[0]["saved"])
        self.assertFalse(networks[0]["connected"])

    def test_wifi_list_marks_connected_network_and_removes_duplicates(self):
        """确认当前网络置顶显示为已连接，并按名称去除重复热点。"""
        networks = merge_wifi_networks([
            {"ssid": "当前网络", "rssi": -70, "security": 3},
            {"ssid": "当前网络", "rssi": -35, "security": 3},
            {"ssid": "其他网络", "rssi": -20, "security": 0},
        ], {
            "ssid": "当前网络",
            "connected": True,
            "rssi": -35,
        })

        self.assertEqual(["当前网络", "其他网络"], [item["ssid"] for item in networks])
        self.assertTrue(networks[0]["connected"])
        self.assertEqual(-35, networks[0]["rssi"])

    def test_wifi_connect_writes_worker_command_without_exposing_other_settings(self):
        """确认 Wi-Fi 连接命令仅携带用户输入的名称与密钥。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        self.assertTrue(application._request_wifi_connect("测试网络", "测试密钥"))

        command = application.worker_process.stdin.write.call_args.args[0]
        payload = json.loads(command.removeprefix("WIFI_CONNECT:"))
        self.assertEqual({"ssid": "测试网络", "password": "测试密钥"}, payload)
        application.worker_process.stdin.flush.assert_called_once_with()

    def test_wifi_forget_writes_worker_command_with_selected_ssid(self):
        """确认忘记网络命令只携带用户选中的已保存网络名称。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.worker_process = mock.Mock()
        application.worker_process.poll.return_value = None

        self.assertTrue(application._request_wifi_forget("已保存网络"))

        command = application.worker_process.stdin.write.call_args.args[0]
        payload = json.loads(command.removeprefix("WIFI_FORGET:"))
        self.assertEqual({"ssid": "已保存网络"}, payload)
        application.worker_process.stdin.flush.assert_called_once_with()

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
        """确认设置窗口已打开时只请求恢复，不会重复创建线程。"""
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

    def test_device_probe_command_can_override_saved_websocket_url(self):
        """确认局域网候选地址会覆盖已保存地址，且不会产生重复参数。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application._worker_command = mock.Mock(return_value=[
            "pico-monitor.exe", "--worker", "--websocket-url", "ws://192.168.1.8:8765/pv1",
        ])

        command = application._device_probe_command("ws://192.168.1.20:8765/pv1")

        self.assertEqual(1, command.count("--websocket-url"))
        self.assertIn("ws://192.168.1.20:8765/pv1", command)
        self.assertNotIn("ws://192.168.1.8:8765/pv1", command)

    def test_websocket_url_is_persisted_and_applied_to_worker(self):
        """确认发现的 WebSocket 地址保存后会在下次启动传给工作进程。"""
        path = Path(self.temporary_directory.name) / "settings.json"
        store = TraySettingsStore(path)
        settings = dict(DEFAULT_SETTINGS, websocket_url="ws://192.168.1.20:8765/pv1")

        store.save(settings)
        arguments = apply_worker_arguments(["--worker"], store.load())

        index = arguments.index("--websocket-url")
        self.assertEqual("ws://192.168.1.20:8765/pv1", arguments[index + 1])

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

    def test_websocket_connection_log_with_space_updates_snapshot(self):
        """确认实际 WebSocket 握手日志中的空格不会阻止连接状态解析。"""
        connection = WorkerControllerMixin._parse_device_connection(
            "2026-07-15 10:27:14,370 [INFO] "
            "[WebSocket 连接] ws://192.168.0.224:8765/pv1 "
            "握手成功：开发板=ESP32-S3，LCD=st7789-2inch-8pin-a，"
            "屏幕方案=st7789vw_2inch，固件版本=development，"
            "分辨率=240x320，Wi-Fi支持=是"
        )

        self.assertIsNotNone(connection)
        self.assertTrue(connection["connected"])
        self.assertEqual("WebSocket", connection["transport"])
        self.assertEqual("ESP32-S3", connection["board_model"])
        self.assertTrue(connection["wifi_supported"])

    def test_rediscovered_websocket_address_is_persisted(self):
        """确认重连扫描得到的新 Wi-Fi 地址会保存供后续启动使用。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.device_connection_lock = threading.Lock()
        application.current_device_connection = {"connected": False}
        application.device_connection_messages = queue.Queue()
        application.settings = dict(DEFAULT_SETTINGS, websocket_url="ws://192.168.0.10:8765/pv1")
        application.settings_store = mock.Mock()
        application.icon = None

        application._update_device_connection({
            "connected": True,
            "transport": "WebSocket",
            "address": "ws://192.168.0.224:8765/pv1",
        })

        self.assertEqual(
            application.settings["websocket_url"],
            "ws://192.168.0.224:8765/pv1",
        )
        application.settings_store.save.assert_called_once_with(application.settings)

    def test_device_connection_change_produces_success_and_failure_notifications(self):
        """确认连接成功和随后断开各产生一次托盘通知。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.device_connection_lock = threading.Lock()
        application.current_device_connection = {"connected": None}
        application.device_connection_messages = queue.Queue()
        application.icon = mock.Mock()

        application._update_device_connection({
            "connected": True,
            "address": "ws://192.168.1.20:8765/pv1",
        })
        application._update_device_connection({
            "connected": False,
            "message": "连接超时",
        })
        application._update_device_connection({
            "connected": False,
            "message": "重复失败",
        })

        self.assertEqual(2, application.icon.notify.call_count)
        self.assertIn("设备连接成功", application.icon.notify.call_args_list[0].args[0])
        self.assertIn("设备连接已断开", application.icon.notify.call_args_list[1].args[0])

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
        """确认每个内置样式都提供规范中文显示名称。"""
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
        process.stdout.close.assert_not_called()
        self.assertIsNone(application.worker_process)

    def test_log_collector_accepts_output_closed_during_worker_stop(self):
        """确认停止进程时输出流已关闭不会造成日志线程未处理异常。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.log_path = Path(self.temporary_directory.name) / "pico-monitor.log"
        application.log_file_lock = threading.Lock()
        application.stopping = threading.Event()
        application.icon = None
        process = mock.Mock()
        process.stdout = io.StringIO()
        process.stdout.close()
        process.poll.return_value = 0
        process.wait.return_value = 0
        application.worker_process = process

        application._collect_output(process)

        process.wait.assert_called_once_with()

    def test_log_collector_restarts_unexpectedly_exited_worker(self):
        """确认托盘仍运行时后台 Monitor 异常退出会延迟自动拉起。"""
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application.log_path = Path(self.temporary_directory.name) / "pico-monitor.log"
        application.log_file_lock = threading.Lock()
        application.stopping = mock.Mock()
        application.stopping.is_set.return_value = False
        application.stopping.wait.return_value = False
        application.icon = mock.Mock()
        application._start_worker = mock.Mock()
        process = mock.Mock()
        process.stdout = io.StringIO("")
        process.wait.return_value = 7
        application.worker_process = process

        application._collect_output(process)

        application.stopping.wait.assert_called_once_with(5.0)
        application._start_worker.assert_called_once_with()
        application.icon.notify.assert_called_once()

    def test_device_probe_output_uses_current_pico_prefix(self):
        """确认设备管理页面能够解析单次探测实际输出的 Pico 字段。"""
        self.assertEqual(
            ("board_model", "esp32-s3"),
            parse_device_information_line("Pico 开发板型号：esp32-s3\n"),
        )
        self.assertEqual(
            ("firmware_version", "1.2.3"),
            parse_device_information_line("Pico 固件版本：1.2.3\n"),
        )
        self.assertEqual(
            ("wifi_supported", "是"),
            parse_device_information_line("Pico Wi-Fi 支持：是\n"),
        )

    def test_managed_arguments_are_replaced_without_losing_worker_flag(self):
        """确认托盘参数覆盖配置时保留后台工作模式标志。"""
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
        """确认首次运行会把已有命令行配置迁移到托盘配置。"""
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
        """确认配置读取忽略未知字段，并为缺失字段补齐默认值。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"lcd_style": "simple", "unknown": 1}), encoding="utf-8")
            settings = TraySettingsStore(path).load()
        self.assertEqual(settings["lcd_style"], "simple")
        self.assertEqual(settings["ping_target"], DEFAULT_SETTINGS["ping_target"])
        self.assertNotIn("unknown", settings)

    def test_store_loads_and_normalizes_lan_probe_settings(self):
        """确认局域网探测参数可由配置文件提供，并规范化协议路径。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({
                "lan_probe_port": "9876",
                "lan_probe_path": "device",
                "lan_probe_timeout": "0.8",
                "lan_probe_max_workers": "32",
            }), encoding="utf-8")
            settings = TraySettingsStore(path).load()
        self.assertEqual(settings["lan_probe_port"], 9876)
        self.assertEqual(settings["lan_probe_path"], "/device")
        self.assertEqual(settings["lan_probe_timeout"], 0.8)
        self.assertEqual(settings["lan_probe_max_workers"], 32)

    def test_store_repairs_invalid_lan_probe_settings(self):
        """确认无效局域网探测参数会恢复为安全默认值。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({
                "lan_probe_port": 70000,
                "lan_probe_path": "",
                "lan_probe_timeout": 0,
                "lan_probe_max_workers": -1,
            }), encoding="utf-8")
            settings = TraySettingsStore(path).load()
        for name in (
                "lan_probe_port", "lan_probe_path", "lan_probe_timeout",
                "lan_probe_max_workers",
        ):
            self.assertEqual(settings[name], DEFAULT_SETTINGS[name])

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
