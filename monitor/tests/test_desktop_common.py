"""桌面公共层迁移、旧入口兼容及 Windows/Linux 启动契约回归。"""

import importlib
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

from desktop.common.application import DesktopApplication
from desktop.common.entry import desktop_requested, start_desktop
from desktop.common.platform import data_directory, open_path, subprocess_flags
from desktop.common.posix_application import DesktopIcon, PosixDesktopApplication
from desktop.common.settings import TraySettingsStore, apply_worker_arguments
from desktop.common.single_instance import SingleInstanceLock
from desktop.common.ui_api.bridge import WebViewBridge
from desktop.common.ui_api.webview import WebUiMixin
from desktop.linux.application import LinuxAutostart
from monitor_core.arguments import parse_monitor_arguments


MONITOR_ROOT = Path(__file__).resolve().parents[1]


class EventHook:
    """模拟 pywebview 关闭事件，保留应用注册的唯一处理器。"""

    def __init__(self):
        """初始化空事件处理器。"""
        self.callback = None

    def __iadd__(self, callback):
        """保存处理器并返回事件对象。"""
        self.callback = callback
        return self


class DesktopCommonTest(unittest.TestCase):
    """验证迁移后保留配置、业务 action 和默认服务入口。"""

    def test_legacy_modules_share_implementation_identity(self):
        """旧模块与新模块是同一对象，原有测试补丁继续生效。"""
        pairs = {
            "win.settings": "desktop.common.settings",
            "win.worker_controller": "desktop.common.worker_controller",
            "win.log_service": "desktop.common.log_service",
            "win.constants": "desktop.common.constants",
            "web_admin": "desktop.common.http_server",
            "win.ui-web-api.bridge": "desktop.common.ui_api.bridge",
            "win.ui-web-api.webview": "desktop.common.ui_api.webview",
        }
        for old, new in pairs.items():
            with self.subTest(module=old):
                self.assertIs(importlib.import_module(old), importlib.import_module(new))

    @unittest.skipUnless(sys.platform == "win32", "仅在 Windows 验证原生兼容入口")
    def test_windows_class_and_ui_identity(self):
        """Windows 托盘、启动项和旧 Tk 模块保持真实实现身份。"""
        for old, new in {
            "win.tray": "desktop.win.tray", "win.autostart": "desktop.win.autostart",
            "win.power_events": "desktop.win.power_events", "win.ui.device_window": "desktop.win.ui.device_window",
        }.items():
            with self.subTest(module=old):
                self.assertIs(importlib.import_module(old), importlib.import_module(new))

    def test_common_and_linux_import_without_gui(self):
        """隔离进程确认公共桥接和 Linux 服务不会加载桌面或 Cocoa。"""
        script = "import sys; import desktop.common.ui_api; import desktop.linux.bridge; assert not any(n in sys.modules for n in ('desktop.win.tray','webview','pystray','AppKit','UserNotifications'))"
        subprocess.run([sys.executable, "-B", "-c", script], cwd=MONITOR_ROOT, check=True,
                       capture_output=True, timeout=30)

    def test_linux_default_remains_headless(self):
        """Linux 即使冻结也必须显式启用桌面，worker 总是优先。"""
        arguments = types.SimpleNamespace(desktop=False, worker=False, pico_info=False, upgrade_pico=False, update=False)
        with mock.patch("desktop.common.entry.sys.platform", "linux"), mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(desktop_requested(arguments))
            arguments.desktop = True
            self.assertTrue(desktop_requested(arguments))
            arguments.worker = True
            self.assertFalse(desktop_requested(arguments))

    def test_frozen_windows_and_mac_default_to_desktop(self):
        """Windows/Mac 冻结入口默认启动桌面，但 CLI 查询不启动 GUI。"""
        arguments = types.SimpleNamespace(desktop=False, worker=False, pico_info=False, upgrade_pico=False, update=False)
        for platform in ("win32", "darwin"):
            with self.subTest(platform=platform), mock.patch("desktop.common.entry.sys.platform", platform), mock.patch.object(sys, "frozen", True, create=True):
                self.assertTrue(desktop_requested(arguments))
                arguments.pico_info = True
                self.assertFalse(desktop_requested(arguments))
                arguments.pico_info = False

    def test_mock_attributes_do_not_accidentally_enable_desktop(self):
        """避免新增 desktop 字段把旧测试的动态 Mock 解释为显式开启。"""
        arguments = mock.Mock(worker=False, pico_info=False, upgrade_pico=False, update=False)
        with mock.patch("desktop.common.entry.sys.platform", "linux"):
            self.assertFalse(desktop_requested(arguments))

    def test_desktop_argument_is_accepted_for_worker(self):
        """桌面转发原始参数时，子进程能够解析 --desktop 与 --worker。"""
        arguments = parse_monitor_arguments(["--desktop", "--worker"])
        self.assertTrue(arguments.desktop)
        self.assertTrue(arguments.worker)
        self.assertFalse(desktop_requested(arguments))

    def test_platform_subprocess_flags(self):
        """保留 Windows 隐藏控制台标志，Linux/Mac 使用零标志。"""
        for platform, expected in (("win32", 0x08000000), ("darwin", 0), ("linux", 0)):
            with self.subTest(platform=platform), mock.patch("desktop.common.platform.sys.platform", platform):
                self.assertEqual(expected, subprocess_flags())

    def test_platform_data_directories(self):
        """Windows 路径不变，Mac 使用用户 Library，Linux 使用 XDG。"""
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "local-app", "XDG_DATA_HOME": "xdg-data"}):
            with mock.patch("desktop.common.platform.sys.platform", "win32"):
                self.assertEqual(Path("local-app/PicoMonitor"), data_directory())
            with mock.patch("desktop.common.platform.sys.platform", "darwin"):
                self.assertEqual(Path.home() / "Library/Application Support/OmniWatch", data_directory())
            with mock.patch("desktop.common.platform.sys.platform", "linux"):
                self.assertEqual(Path("xdg-data/omniwatch"), data_directory())

    def test_open_path_uses_argument_array(self):
        """中文、空格和 shell 字符不会改变平台文件打开命令。"""
        path = MONITOR_ROOT / "中文 & 文件.log"
        for platform, executable in (("win32", "explorer.exe"), ("darwin", "/usr/bin/open"), ("linux", "xdg-open")):
            with self.subTest(platform=platform), mock.patch("desktop.common.platform.sys.platform", platform), mock.patch("desktop.common.platform.subprocess.Popen") as popen:
                open_path(path, reveal=True)
                self.assertEqual(executable, popen.call_args.args[0][0])
                self.assertNotIn("shell", popen.call_args.kwargs)

    def test_existing_settings_round_trip(self):
        """现有设置字段和中文样式信息迁移后保持兼容。"""
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            values = store.load()
            values["port"] = "COM8"
            values["lcd_brightness"] = 38
            store.save(values)
            restored = store.load()
            self.assertEqual("COM8", restored["port"])
            self.assertEqual(38, restored["lcd_brightness"])
            self.assertIn("--worker", apply_worker_arguments(["--worker"], restored))
            self.assertFalse(store.path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_log_directory_action_uses_platform_adapter(self):
        """公共日志 action 不引用 explorer 或 Windows 子进程标志。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch("desktop.common.ui_api.log_api.open_path") as opener:
            path = Path(directory) / "中文 数据"
            bridge = WebViewBridge(types.SimpleNamespace(data_directory=path))
            response = bridge.invoke("system.openDataDirectory", {})
            self.assertTrue(response["ok"], response)
            self.assertTrue(path.is_dir())
            opener.assert_called_once_with(path)

    def test_close_hides_but_exit_stops_worker(self):
        """普通关窗不停止采集；显式退出设置标志并回收窗口和 worker。"""
        application = DesktopApplication.__new__(DesktopApplication)
        application.stopping = threading.Event()
        application._stop_worker = mock.Mock()
        application._resource_path = mock.Mock(return_value=Path(__file__))
        application.webview_bridge = mock.Mock()
        window = mock.Mock()
        window.events = types.SimpleNamespace(closing=EventHook())
        webview = mock.Mock()
        webview.create_window.return_value = window
        with mock.patch.dict(sys.modules, {"webview": webview}):
            WebUiMixin._initialize_webview(application)
        self.assertFalse(window.events.closing.callback())
        window.hide.assert_called_once()
        application._stop_worker.assert_not_called()
        icon = mock.Mock()
        application._exit(icon, None)
        self.assertTrue(application.stopping.is_set())
        self.assertTrue(window.events.closing.callback())
        application._stop_worker.assert_called_once()
        window.destroy.assert_called_once()

    def test_clipboard_action_is_controlled(self):
        """剪贴板只允许受限文本，不暴露原生平台对象。"""
        application = types.SimpleNamespace(_copy_text=mock.Mock())
        bridge = WebViewBridge(application)
        self.assertTrue(bridge.invoke("system.copyText", {"text": "中文日志"})["ok"])
        application._copy_text.assert_called_once_with("中文日志")
        self.assertFalse(bridge.invoke("system.copyText", {"text": ["非法"]})["ok"])
        self.assertFalse(bridge.invoke("system.copyText", {"text": "中" * 800000})["ok"])

    def test_desktop_notification_failure_does_not_escape(self):
        """系统通知未授权或抛错时不终止托盘业务。"""
        native = mock.Mock()
        notifier = mock.Mock(side_effect=RuntimeError("通知未授权"))
        icon = DesktopIcon(native, notifier)
        with self.assertLogs("pico-monitor.desktop", level="ERROR"):
            icon.notify("测试")
        icon.update_menu()
        native.update_menu.assert_called_once()

    def test_posix_cleanup_on_gui_failure(self):
        """主 GUI 循环异常时仍回收平台监听、HTTP、托盘、worker 和锁。"""
        self._run_posix_cleanup_test(False)

    def test_posix_http_cleanup_failure_still_stops_worker(self):
        """HTTP 停止失败不能跳过 worker、托盘与单实例锁清理。"""
        self._run_posix_cleanup_test(True)

    def _run_posix_cleanup_test(self, http_failure):
        """构造无原生 GUI 的生命周期替身，检查不同异常路径的资源回收。"""
        application = PosixDesktopApplication.__new__(PosixDesktopApplication)
        application.data_directory = Path("unused")
        application.stopping = threading.Event()
        for name in ("_prepare_webview_runtime", "_initialize_webview", "_start_worker", "_start_platform_services", "_stop_platform_services", "_apply_http_admin_settings", "_stop_http_admin", "_stop_worker"):
            setattr(application, name, mock.Mock())
        application._native_icon_options = mock.Mock(return_value={})
        application._create_image = mock.Mock()
        application._build_menu = mock.Mock()
        application._start_webview_loop = mock.Mock(side_effect=RuntimeError("GUI 失败"))
        application._notify = mock.Mock()
        application.icon = None
        if http_failure:
            application._stop_http_admin.side_effect = RuntimeError("HTTP 停止失败")
        with mock.patch.dict(sys.modules, {"pystray": mock.Mock()}), mock.patch("desktop.common.posix_application.SingleInstanceLock") as lock:
            with self.assertRaisesRegex(RuntimeError, "HTTP 停止失败" if http_failure else "GUI 失败"):
                application.run()
            lock.return_value.close.assert_called_once()
        application._stop_worker.assert_called_once()
        application._stop_platform_services.assert_called_once()
        self.assertTrue(application.stopping.is_set())

    @unittest.skipIf(sys.platform == "win32", "POSIX 文件锁由 Linux/Mac CI 原生验证")
    def test_posix_single_instance_lock(self):
        """两个独立文件句柄不能同时持有单实例锁，释放后可重新获取。"""
        with tempfile.TemporaryDirectory() as directory:
            first = SingleInstanceLock(Path(directory) / "desktop.lock")
            second = SingleInstanceLock(first.path)
            try:
                self.assertTrue(first.acquire())
                self.assertFalse(second.acquire())
                first.close()
                self.assertTrue(second.acquire())
            finally:
                first.close()
                second.close()

    def test_linux_autostart_round_trip(self):
        """Linux 只管理自己的 XDG 启动项，含空格参数正确转义。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
            autostart = LinuxAutostart(["/usr/bin/python3", "中文 程序.py", "--desktop"])
            autostart.set_enabled(True)
            self.assertTrue(autostart.is_enabled())
            self.assertIn('"中文 程序.py"', autostart.path.read_text(encoding="utf-8"))
            autostart.set_enabled(False)
            self.assertFalse(autostart.is_enabled())


if __name__ == "__main__":
    unittest.main()
