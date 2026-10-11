"""macOS 桌面适配、启动项、更新安全和打包契约测试。"""

import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import zipfile
import yaml
from pathlib import Path
from unittest import mock

import custom_data.support as plugin_support
from desktop.macos.application import MacOsDesktopApplication
from desktop.macos.autostart import LAUNCH_AGENT_LABEL, MacOsAutostart
from desktop.macos.build import copy_plugin_runtime, deployment_versions, sign_plugin_runtime, validate_runtime, verify_dmg_signature
from desktop.macos.native import MacOsNotifications, MacOsWakeObserver, copy_text
from desktop.macos.update import (
    APP_NAME, BUNDLE_IDENTIFIER, MacOsReleaseUpdater, application_bundle,
    apply_update, current_architecture, validate_archive, verify_bundle, _wait_for_parent,
)


MONITOR_ROOT = Path(__file__).resolve().parents[1]


class MacOsDesktopTest(unittest.TestCase):
    """通过平台替身验证 macOS 行为，不把 mock 测试当成 Mac 真机验收。"""

    def test_runtime_copy_keeps_source_managed_and_initializes_private_copy(self):
        """只在新运行时副本省略 uv 标记，保留原环境、标准库和内部链接。"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "managed-python"
            library = source / "lib/python3.13"
            library.mkdir(parents=True)
            marker = library / "EXTERNALLY-MANAGED"
            marker.write_text("[externally-managed]\nError=由 uv 管理\n", encoding="utf-8")
            (library / "stdlib.py").write_text("# 标准库文件\n", encoding="utf-8")
            cache = library / "__pycache__"
            cache.mkdir()
            (cache / "stdlib.pyc").write_bytes("缓存".encode("utf-8"))
            binary = source / "bin"
            binary.mkdir()
            (binary / "python3.13").write_bytes("解释器".encode("utf-8"))
            # 链接可迁移性是原生 Mac 打包契约；不要求 Windows 测试机创建符号链接。
            if sys.platform == "darwin":
                (binary / "python3").symlink_to("python3.13")
            destination = Path(directory) / "plugin-runtime"
            copy_plugin_runtime(source, destination)
            self.assertIn("由 uv 管理", marker.read_text(encoding="utf-8"))
            self.assertFalse((destination / "lib/python3.13/EXTERNALLY-MANAGED").exists())
            self.assertEqual((library / "stdlib.py").read_bytes(),
                             (destination / "lib/python3.13/stdlib.py").read_bytes())
            self.assertFalse((destination / "lib/python3.13/__pycache__").exists())
            self.assertTrue(cache.is_dir())
            if sys.platform == "darwin":
                self.assertTrue((destination / "bin/python3").is_symlink())
                self.assertEqual("python3.13", os.readlink(destination / "bin/python3"))

    def test_runtime_validation_forbids_cache_in_all_python_children(self):
        """venv 与 ensurepip 分开运行，禁止签名后的共享标准库产生新增缓存。"""
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve() / "plugin-runtime"
            (runtime / "bin").mkdir(parents=True)
            (runtime / "bin/python3").write_bytes(b"test")
            result = types.SimpleNamespace(stdout=json.dumps({"prefix": str(runtime), "architecture": "x86_64"}))
            with mock.patch("desktop.macos.build.run", return_value=result) as execute:
                validate_runtime(runtime, "x86_64")
            commands = [call.args[0] for call in execute.call_args_list]
            self.assertTrue(any("venv" in command and "--without-pip" in command for command in commands))
            self.assertTrue(any("ensurepip" in command for command in commands))
            for call in execute.call_args_list:
                self.assertIn("-B", call.args[0])
                self.assertEqual(call.kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
                self.assertNotIn("PYTHONHOME", call.kwargs["env"])
                self.assertNotIn("PYTHONPATH", call.kwargs["env"])
                if "ensurepip" in call.args[0]:
                    self.assertNotIn("-I", call.args[0])
                    self.assertIn("-s", call.args[0])

    def test_final_dmg_signature_failure_detaches_own_mount(self):
        """最终 DMG 签名失败时终止构建，仍卸载本次只读挂载卷。"""
        mount = Path("/Volumes/OmniWatch-test")
        attachment = types.SimpleNamespace(stdout=plistlib.dumps({"system-entities": [{"mount-point": str(mount)}]}))
        with mock.patch("desktop.macos.build.run", side_effect=[None, attachment, subprocess.CalledProcessError(1, "codesign"), None]) as execute:
            with self.assertRaises(subprocess.CalledProcessError):
                verify_dmg_signature(Path("test.dmg"))
        self.assertIn("-readonly", execute.call_args_list[1].args[0])
        self.assertEqual(execute.call_args_list[-1].args[0], ["/usr/bin/hdiutil", "detach", mount])

    def test_final_dmg_signature_success_checks_packaged_app(self):
        """发行门禁检查 DMG 内的应用，而不是打包前的临时源目录。"""
        mount = Path("/Volumes/OmniWatch-test")
        attachment = types.SimpleNamespace(stdout=plistlib.dumps({"system-entities": [{"mount-point": str(mount)}]}))
        with mock.patch("desktop.macos.build.run", side_effect=[None, attachment, None, None]) as execute:
            verify_dmg_signature(Path("test.dmg"))
        self.assertEqual(execute.call_args_list[2].args[0],
                         ["/usr/bin/codesign", "--verify", "--deep", "--strict", mount / "OmniWatch.app"])

    def test_application_uses_system_webkit(self):
        """Mac 不传 edgechromium 或 Qt，不检查 WebView2 注册表。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(sys.modules, {"webview": mock.Mock()}) as modules:
            application.data_directory = Path(directory)
            application._start_webview_loop()
            arguments = modules["webview"].start.call_args.kwargs
            self.assertNotIn("gui", arguments)
            self.assertFalse(arguments["private_mode"])
            self.assertTrue((Path(directory) / "webview").is_dir())

    def test_menu_navigation_does_not_wait_on_cocoa_main_thread(self):
        """菜单恢复在主线程执行，Vue JavaScript 结果在后台等待，避免原生死锁。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
        application.stopping = threading.Event()
        application.webview_window = mock.Mock()
        application.icon = None
        callbacks = []
        main_thread = threading.get_ident()
        evaluated = threading.Event()
        evaluated_on = []
        restored_on = []
        native = mock.Mock()

        def record_restore():
            """记录恢复原生窗口的线程。"""
            restored_on.append(threading.get_ident())

        def record_evaluation(script):
            """记录共享导航脚本与后台线程，并通知用例完成。"""
            evaluated_on.append((threading.get_ident(), script))
            evaluated.set()

        application.webview_window.restore.side_effect = record_restore
        application.webview_window.evaluate_js.side_effect = record_evaluation
        helper = mock.Mock(callAfter=mock.Mock(side_effect=callbacks.append))
        with mock.patch.dict(sys.modules, {"AppKit": native, "PyObjCTools.AppHelper": helper}):
            application._show_web_page("settings")
            application.webview_window.restore.assert_not_called()
            application.webview_window.evaluate_js.assert_not_called()
            self.assertEqual(1, len(callbacks))
            callbacks[0]()
            self.assertTrue(evaluated.wait(2), "后台导航未执行")
        self.assertEqual([main_thread], restored_on)
        self.assertNotEqual(main_thread, evaluated_on[0][0])
        self.assertIn("omniwatch:navigate", evaluated_on[0][1])
        self.assertIn('"settings"', evaluated_on[0][1])
        application.webview_window.show.assert_called_once_with()
        native.NSApplication.sharedApplication.return_value.activateIgnoringOtherApps_.assert_called_once_with(True)

    def test_menu_navigation_stops_before_scheduled_window_operation(self):
        """退出后既不投递窗口任务，也不执行退出前排队的窗口恢复回调。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
        application.stopping = threading.Event()
        application.webview_window = mock.Mock()
        callbacks = []
        helper = mock.Mock(callAfter=mock.Mock(side_effect=callbacks.append))
        with mock.patch.dict(sys.modules, {"AppKit": mock.Mock(), "PyObjCTools.AppHelper": helper}), mock.patch("desktop.macos.application.threading.Thread") as thread:
            application._show_web_page("settings")
            application.stopping.set()
            callbacks[0]()
            application._show_web_page("logs")
            self.assertEqual(1, helper.callAfter.call_count)
            application.webview_window.restore.assert_not_called()
            thread.assert_not_called()

    def test_private_runtime_signing_keeps_release_and_dev_modes_separate(self):
        """开发签名不请求时间戳，正式签名保持 hardened runtime，二者均严格验证。"""
        binary = Path("OmniWatch.app/Contents/Resources/plugin-runtime/bin/python3")
        for identity in ("-", "Developer ID Application: 测试团队"):
            with self.subTest(identity=identity), mock.patch("desktop.macos.build.macho_files", return_value=[binary]), mock.patch("desktop.macos.build.run") as command:
                sign_plugin_runtime(Path("OmniWatch.app"), identity)
                sign_arguments = command.call_args_list[0].args[0]
                self.assertEqual(identity != "-", "--timestamp" in sign_arguments)
                self.assertEqual(identity != "-", "--options" in sign_arguments)
                self.assertIn("--entitlements", sign_arguments)
                self.assertEqual(["/usr/bin/codesign", "--verify", "--deep", "--strict", Path("OmniWatch.app")], command.call_args.args[0])

    def test_tray_shares_nsapplication(self):
        """菜单栏复用 Cocoa 共享应用，避免与 WebView 争夺主循环。"""
        native = mock.Mock()
        shared = native.NSApplication.sharedApplication.return_value
        with mock.patch.dict(sys.modules, {"AppKit": native}):
            application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
            self.assertIs(shared, application._native_icon_options()["darwin_nsapplication"])

    def test_cocoa_import_precedes_accessory_policy(self):
        """先加载会修改 Dock 策略的 Cocoa 模块，再恢复菜单栏模式。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
        order = mock.Mock()
        native = mock.Mock(NSApplicationActivationPolicyAccessory=1)
        order.attach_mock(native.NSApplication.sharedApplication.return_value.setActivationPolicy_, "policy")
        with mock.patch("desktop.common.posix_application.PosixDesktopApplication._prepare_webview_runtime"), mock.patch("desktop.macos.application.import_module") as load, mock.patch.dict(sys.modules, {"AppKit": native}):
            order.attach_mock(load, "load")
            application._prepare_webview_runtime()
        self.assertEqual([mock.call.load("webview.platforms.cocoa"), mock.call.policy(1)], order.mock_calls)

    def test_qt_environment_cannot_override_cocoa(self):
        """临时屏蔽用户指定的 Qt 后端，退出 GUI 循环后恢复原环境。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)

        def check_backend(**options):
            """确认调用系统默认 Mac 后端时不存在 Qt 环境覆盖。"""
            self.assertNotIn("PYWEBVIEW_GUI", os.environ)
            self.assertNotIn("gui", options)

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"PYWEBVIEW_GUI": "qt"}), mock.patch.dict(sys.modules, {"webview": mock.Mock(start=mock.Mock(side_effect=check_backend))}):
            application.data_directory = Path(directory)
            application._start_webview_loop()
            self.assertEqual("qt", os.environ["PYWEBVIEW_GUI"])

    def test_resume_reuses_worker_command(self):
        """唤醒发送既有 RESUME_PROBE，退出阶段不再触发重连。"""
        application = MacOsDesktopApplication.__new__(MacOsDesktopApplication)
        application.stopping = threading.Event()
        application._write_worker_command = mock.Mock()
        application._handle_resume()
        application._write_worker_command.assert_called_once_with("RESUME_PROBE\n")
        application.stopping.set()
        application._handle_resume()
        self.assertEqual(1, application._write_worker_command.call_count)

    def test_wake_observer_registers_and_releases(self):
        """原生唤醒回调持有 token，并且重复关闭只注销一次。"""
        callback = mock.Mock()
        center = mock.Mock()
        appkit = mock.Mock(NSWorkspaceDidWakeNotification="didWake")
        appkit.NSWorkspace.sharedWorkspace.return_value.notificationCenter.return_value = center
        observer = MacOsWakeObserver(callback)
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "Foundation": mock.Mock()}):
            observer.start()
            observer.start()
        center.addObserverForName_object_queue_usingBlock_.assert_called_once()
        center.addObserverForName_object_queue_usingBlock_.call_args.args[3](None)
        callback.assert_called_once()
        observer.stop()
        observer.stop()
        center.removeObserver_.assert_called_once()

    def test_native_notification_respects_authorization(self):
        """通知授权拒绝时不提交，授权通过后才发送一次性通知。"""
        native = mock.Mock(UNAuthorizationOptionAlert=1, UNAuthorizationOptionSound=2)
        center = native.UNUserNotificationCenter.currentNotificationCenter.return_value
        notifications = MacOsNotifications()
        with mock.patch.dict(sys.modules, {"UserNotifications": native}):
            notifications.start()
            completed = center.requestAuthorizationWithOptions_completionHandler_.call_args.args[1]
            completed(False, None)
            self.assertFalse(notifications.send("测试", "OmniWatch"))
            center.addNotificationRequest_withCompletionHandler_.assert_not_called()
            completed(True, None)
            self.assertTrue(notifications.send("中文通知", "OmniWatch"))
        center.addNotificationRequest_withCompletionHandler_.assert_called_once()

    def test_native_clipboard_reports_actual_success(self):
        """剪贴板写入失败不能提前返回成功，主线程直接操作 AppKit。"""
        appkit = mock.Mock(NSPasteboardTypeString="public.utf8-plain-text")
        board = appkit.NSPasteboard.generalPasteboard.return_value
        board.setString_forType_.return_value = True
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "PyObjCTools": mock.Mock(), "PyObjCTools.AppHelper": mock.Mock()}):
            copy_text("中文内容")
            board.setString_forType_.assert_called_once_with("中文内容", "public.utf8-plain-text")
            board.setString_forType_.return_value = False
            with self.assertRaisesRegex(RuntimeError, "剪贴板"):
                copy_text("失败")

    def test_launch_agent_round_trip(self):
        """使用用户 gui 域注册启动项，不使用 root 或 KeepAlive 重启退出应用。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch("desktop.macos.autostart.os.getuid", return_value=501, create=True), mock.patch("desktop.macos.autostart.subprocess.run") as run:
            autostart = MacOsAutostart(["/用户/应用 程序.app/Contents/MacOS/pico-monitor", "--desktop"], directory)
            autostart.set_enabled(True)
            self.assertTrue(autostart.is_enabled())
            values = plistlib.loads(autostart.path.read_bytes())
            self.assertEqual(LAUNCH_AGENT_LABEL, values["Label"])
            self.assertFalse(values["KeepAlive"])
            self.assertTrue(values["RunAtLoad"])
            self.assertIn("gui/501", run.call_args.args[0])
            autostart.set_enabled(False)
            self.assertFalse(autostart.is_enabled())

    def test_launch_agent_failure_restores_previous_file(self):
        """launchctl 加载失败时还原原启动项内容，避免丢失既有设置。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch("desktop.macos.autostart.os.getuid", return_value=501, create=True):
            autostart = MacOsAutostart(["/Applications/OmniWatch.app/Contents/MacOS/pico-monitor"], directory)
            previous = plistlib.dumps({"Label": LAUNCH_AGENT_LABEL, "ProgramArguments": ["/old"]})
            autostart.path.write_bytes(previous)
            with mock.patch("desktop.macos.autostart.subprocess.run", side_effect=[None, RuntimeError("加载失败"), None]):
                with self.assertRaisesRegex(RuntimeError, "加载失败"):
                    autostart.set_enabled(True)
            self.assertEqual(previous, autostart.path.read_bytes())

    def test_launch_agent_new_file_is_removed_on_failure(self):
        """首次创建启动项失败时不留下错误的已启用状态。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch("desktop.macos.autostart.os.getuid", return_value=501, create=True), mock.patch("desktop.macos.autostart.subprocess.run", side_effect=[None, RuntimeError("加载失败")]):
            autostart = MacOsAutostart(["/application"], directory)
            with self.assertRaises(RuntimeError):
                autostart.set_enabled(True)
            self.assertFalse(autostart.path.exists())

    def test_release_asset_is_architecture_specific(self):
        """Intel 与 Apple Silicon 使用独立 ZIP，拒绝开发包和错误架构。"""
        updater = MacOsReleaseUpdater("owner/repo", "1.0.0")
        for machine, architecture in (("arm64", "arm64"), ("aarch64", "arm64"), ("x86_64", "x86_64")):
            with self.subTest(machine=machine), mock.patch("desktop.macos.update.platform.machine", return_value=machine):
                name = "OmniWatch-macos-{}-v1.1.0.zip".format(architecture)
                self.assertEqual(name, updater.select_monitor_asset([{"name": name}], "1.1.0")["name"])
                with self.assertRaises(RuntimeError):
                    updater.select_monitor_asset([{"name": name.replace("-v", "-dev-v")}], "1.1.0")
                with self.assertRaises(RuntimeError):
                    updater.select_monitor_asset([{"name": name}, {"name": name}], "1.1.0")

    def test_unknown_architecture_is_rejected(self):
        """未知架构不能猜测 Intel 或 ARM 更新资源。"""
        with mock.patch("desktop.macos.update.platform.machine", return_value="unknown"):
            with self.assertRaises(RuntimeError):
                current_architecture()

    def test_unsigned_download_is_rejected_before_network(self):
        """应用更新包没有 SHA-256 摘要时不发起下载。"""
        updater = MacOsReleaseUpdater("owner/repo", "1.0.0")
        with mock.patch("desktop.common.release.urllib.request.urlopen") as request:
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                updater.download({"name": "OmniWatch-macos-arm64-v1.1.0.zip"}, ".zip")
        request.assert_not_called()

    def test_application_bundle_rejects_source_python(self):
        """自动更新不能覆盖系统 Python 或源码目录。"""
        self.assertEqual(Path("/Applications/OmniWatch.app").resolve(), application_bundle("/Applications/OmniWatch.app/Contents/MacOS/pico-monitor"))
        with self.assertRaises(RuntimeError):
            application_bundle("/usr/bin/python3")

    def test_archive_rejects_escape_and_foreign_roots(self):
        """拒绝路径穿越、反斜杠、绝对路径及应用外文件。"""
        with tempfile.TemporaryDirectory() as directory:
            for name in ("../outside", "/absolute", "OmniWatch.app/../outside", "Other.app/file", "OmniWatch.app\\file"):
                with self.subTest(name=name):
                    package = Path(directory) / "update.zip"
                    with zipfile.ZipFile(package, "w") as archive:
                        # Windows 的 ZipInfo 构造器会转换反斜杠，显式保留原始归档名。
                        item = zipfile.ZipInfo("placeholder")
                        item.filename = name
                        item.orig_filename = name
                        archive.writestr(item, "内容")
                    with self.assertRaises(RuntimeError):
                        validate_archive(package)

    def test_archive_allows_internal_links_but_not_escape(self):
        """允许 PyInstaller 内部相对链接，拒绝逃出 .app 的链接。"""
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "update.zip"
            for target, valid in (("../Frameworks/library.dylib", True), ("../../../outside", False), ("/etc/passwd", False)):
                with self.subTest(target=target):
                    item = zipfile.ZipInfo("OmniWatch.app/Contents/Resources/library.dylib")
                    item.create_system = 3
                    item.external_attr = (stat.S_IFLNK | 0o777) << 16
                    with zipfile.ZipFile(package, "w") as archive:
                        archive.writestr(item, target)
                    if valid:
                        validate_archive(package)
                    else:
                        with self.assertRaises(RuntimeError):
                            validate_archive(package)

    def test_archive_accepts_ditto_metadata(self):
        """AppleDouble 元数据允许保留，但只能属于当前 .app。"""
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "update.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("OmniWatch.app/Contents/Info.plist", "内容")
                archive.writestr("__MACOSX/OmniWatch.app/Contents/._Info.plist", "元数据")
            validate_archive(package)

    def test_bundle_verification_enforces_team_version_and_architecture(self):
        """同一团队、Bundle ID、Release 版本和 CPU 架构都必须匹配。"""
        with tempfile.TemporaryDirectory() as directory:
            application = Path(directory) / APP_NAME
            (application / "Contents").mkdir(parents=True)
            values = {"CFBundleIdentifier": BUNDLE_IDENTIFIER, "CFBundleExecutable": "pico-monitor", "OmniWatchReleaseVersion": "1.1.0"}
            (application / "Contents/Info.plist").write_bytes(plistlib.dumps(values))

            def command_result(command, **options):
                """提供不同原生命令对应的最小可验证输出。"""
                del options
                output = "arm64" if command[0].endswith("lipo") else "Identifier={}\nTeamIdentifier=ABCDE12345\n".format(BUNDLE_IDENTIFIER)
                return types.SimpleNamespace(stdout=output, stderr="")

            with mock.patch("desktop.macos.update.subprocess.run", side_effect=command_result):
                self.assertEqual("ABCDE12345", verify_bundle(application, "ABCDE12345", "1.1.0", "arm64"))
                for team, version, architecture in (("OTHER12345", "1.1.0", "arm64"), ("ABCDE12345", "1.2.0", "arm64"), ("ABCDE12345", "1.1.0", "x86_64")):
                    with self.subTest(team=team, version=version, architecture=architecture):
                        with self.assertRaises(RuntimeError):
                            verify_bundle(application, team, version, architecture)

    def test_gatekeeper_failure_is_fatal(self):
        """签名或 Gatekeeper 失败时不得继续安装。"""
        with mock.patch("desktop.macos.update.subprocess.run", side_effect=subprocess.CalledProcessError(1, "spctl")):
            with self.assertRaises(subprocess.CalledProcessError):
                verify_bundle(Path("unused"), architecture="arm64")

    def test_update_swap_preserves_backup(self):
        """成功替换后保留旧应用，便于用户恢复，且只启动已安装的新应用。"""
        self._run_swap_test(fail_open=False)

    def test_update_open_failure_rolls_back(self):
        """新应用启动命令失败时恢复旧应用内容。"""
        self._run_swap_test(fail_open=True)

    def test_update_record_failure_does_not_roll_back_started_app(self):
        """新应用启动成功后，写入诊断记录失败不能撤回已经提交的更新。"""
        self._run_swap_test(fail_open=False, fail_record=True)

    def _run_swap_test(self, fail_open, fail_record=False):
        """构造隔离应用目录，验证真实文件重命名与回滚而不调用 Mac 命令。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "omniwatch-macos-update-test"
            source = stage / APP_NAME
            source.mkdir(parents=True)
            (source / "version.txt").write_text("new", encoding="utf-8")
            target = root / "installed.app"
            target.mkdir()
            (target / "version.txt").write_text("old", encoding="utf-8")
            manifest = stage / "update.json"
            manifest.write_text(json.dumps({"source": str(source), "target": str(target), "parent_pid": 123,
                                           "team": "ABCDE12345", "version": "1.1.0", "architecture": "arm64"}), encoding="utf-8")
            if fail_record:
                # 同名目录使诊断文件写入确定失败，不依赖操作系统权限模拟。
                (root / "last-update.json").mkdir()
            with mock.patch("desktop.macos.update.verify_bundle"), mock.patch("desktop.macos.update._wait_for_parent"), mock.patch("desktop.macos.update.subprocess.run", side_effect=RuntimeError("打开失败") if fail_open else None):
                if fail_open:
                    with self.assertRaisesRegex(RuntimeError, "打开失败"):
                        apply_update(manifest)
                else:
                    apply_update(manifest)
            self.assertEqual("old" if fail_open else "new", (target / "version.txt").read_text(encoding="utf-8"))
            backups = list(root.glob(".omniwatch-backup-*.app"))
            self.assertEqual(0 if fail_open else 1, len(backups))

    def test_parent_wait_timeout_does_not_replace(self):
        """更新助手不能无限等待或替换仍在运行的父进程。"""
        with mock.patch("desktop.macos.update.time.monotonic", side_effect=[0, 120]):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                _wait_for_parent(999999)
        with self.assertRaises(ValueError):
            _wait_for_parent(1)

    def test_frozen_plugin_uses_bundled_python(self):
        """Mac 冻结包必须选择完整运行时，缺失时明确失败，不回退到 app 入口。"""
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {}, clear=True):
            contents = Path(directory) / "OmniWatch.app/Contents"
            executable = contents / "MacOS/pico-monitor"
            executable.parent.mkdir(parents=True)
            executable.touch()
            runtime = contents / "Resources/plugin-runtime/bin/python3"
            runtime.parent.mkdir(parents=True)
            runtime.touch()
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch("custom_data.support.sys.platform", "darwin"), mock.patch("custom_data.support.sys.executable", str(executable)):
                self.assertEqual(runtime.resolve(), plugin_support.get_runtime_python().resolve())
                runtime.unlink()
                with self.assertRaises(plugin_support.CustomDataError):
                    plugin_support.get_runtime_python()

    def test_deployment_audit_ignores_sdk_version(self):
        """Mach-O 最低系统与 SDK 版本区分，避免错误宣称 macOS 12 兼容。"""
        output = "Load command 1\n cmd LC_BUILD_VERSION\n platform 1\n minos 11.0\n sdk 15.0\nLoad command 2\n cmd LC_ID_DYLIB\n current version 100.0\n"
        self.assertEqual([(11, 0)], deployment_versions(output))
        self.assertEqual([(10, 13)], deployment_versions("Load command 1\n cmd LC_VERSION_MIN_MACOSX\n version 10.13\n sdk 15.0\n"))

    def test_macos_spec_declares_bundle_and_excludes_windows(self):
        """独立 spec 使用 BUNDLE、完整插件运行时和最低系统声明。"""
        specification = (MONITOR_ROOT / "pico_monitor_macos.spec").read_text(encoding="utf-8")
        for required in ("BUNDLE(", '"LSMinimumSystemVersion": "12.0"', '"LSUIElement": True', "target_arch=target_arch", "MONITOR_MAC_PLUGIN_RUNTIME", '"desktop.win"', '"pystray._darwin"', '"UserNotifications"'):
            with self.subTest(required=required):
                self.assertIn(required, specification)
        self.assertNotIn("uac_admin", specification)
        self.assertNotIn("PresentMon.exe", specification)
        self.assertNotIn('(str(runtime_root), "plugin-runtime")', specification)

    def test_ci_uses_native_architecture_and_separate_dev_packages(self):
        """CI 分别使用 Intel/ARM 原生 runner，正式标签强制签名公证。"""
        workflow = MONITOR_ROOT.parent / ".github/workflows/build-macos-dmg.yml"
        content = workflow.read_text(encoding="utf-8")
        values = yaml.safe_load(content)
        matrix = values["jobs"]["build"]["strategy"]["matrix"]["include"]
        self.assertEqual({("macos-15-intel", "x86_64"), ("macos-15", "arm64")},
                         {(item["runner"], item["architecture"]) for item in matrix})
        environment = values["jobs"]["build"]["env"]
        # GitHub 在分配 runner 之前解析 job 环境，此层不得引用 runner.temp。
        self.assertFalse(any("runner." in str(value) for value in environment.values()))
        trigger = values.get("on", values.get(True))
        self.assertIn("mac_os_support", trigger["push"]["branches"])
        self.assertIn("v*", trigger["push"]["tags"])
        initialization = next(step for step in values["jobs"]["build"]["steps"]
                              if step["name"] == "初始化构建临时路径")
        self.assertIn("$RUNNER_TEMP", initialization["run"])
        self.assertIn("$GITHUB_ENV", initialization["run"])
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", environment["SIGN_RELEASE"])
        for name in ("MACOS_CERTIFICATE_P12_BASE64", "MACOS_CERTIFICATE_PASSWORD", "MACOS_SIGNING_IDENTITY", "MACOS_APPLE_ID", "MACOS_APP_PASSWORD", "MACOS_TEAM_ID", "OMNIWATCH_DOC_TOKEN"):
            self.assertIn("secrets." + name, content)
        self.assertIn("--managed-python 3.13.5", content)
        self.assertIn('uv venv --seed --python "$runtime_python"', content)
        self.assertIn('uv pip install --python "$build_environment/bin/python"', content)
        self.assertIn('"$MONITOR_BUILD_PYTHON" -B tools/run_isolated_tests.py', content)
        self.assertIn('"$MONITOR_BUILD_PYTHON" -B -m desktop.macos.build', content)
        self.assertIn("tools/run_isolated_tests.py", content)
        self.assertEqual("build", values["jobs"]["release"]["needs"])


if __name__ == "__main__":
    unittest.main()
