"""验证 Windows 安装包依赖的构建与运行时部署配置。"""

import unittest
from pathlib import Path


MONITOR_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = MONITOR_ROOT.parent


class WindowsPackagingTest(unittest.TestCase):
    """验证 WebView2 Bootstrapper 已完整接入 Windows 发布链。"""

    def test_inno_setup_installs_webview2_only_when_missing(self):
        """确认安装器携带 Bootstrapper，并在 Runtime 缺失时才运行。"""
        script = (MONITOR_ROOT / "pico_monitor_setup.iss").read_text(
            encoding="utf-8"
        )

        self.assertIn('Source: "{#WebView2Bootstrapper}"', script)
        self.assertIn('Parameters: "/silent /install"', script)
        self.assertIn("Check: not IsWebView2RuntimeInstalled", script)
        self.assertIn("HKCU, WebView2ClientKey", script)
        self.assertIn("HKLM32, WebView2ClientKey", script)

    def test_inno_setup_launches_monitor_with_installer_admin_token(self):
        """确认安装完成页使用管理员令牌启动需要提升权限的 Monitor。"""
        script = (MONITOR_ROOT / "pico_monitor_setup.iss").read_text(
            encoding="utf-8"
        )

        monitor_run_entry = next(
            line
            for line in script.splitlines()
            if line.startswith('Filename: "{app}\\pico-monitor.exe"')
        )
        self.assertIn("postinstall", monitor_run_entry)
        self.assertIn("runascurrentuser", monitor_run_entry)

    def test_local_build_prepares_signed_bootstrapper(self):
        """确认本地构建会下载并校验 Microsoft 签名。"""
        build_script = (MONITOR_ROOT / "build-exe.bat").read_text(
            encoding="utf-8"
        )
        prepare_script = (
            MONITOR_ROOT / "prepare-webview2-bootstrapper.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("prepare-webview2-bootstrapper.ps1", build_script)
        self.assertIn("Get-AuthenticodeSignature", prepare_script)
        self.assertIn("Microsoft Corporation", prepare_script)

    def test_windows_development_launcher_installs_missing_runtime(self):
        """确认源码启动脚本会在 Runtime 缺失时调用官方 Bootstrapper。"""
        launcher = (MONITOR_ROOT / "test-windows.bat").read_text(
            encoding="utf-8"
        )
        prepare_script = (
            MONITOR_ROOT / "prepare-webview2-bootstrapper.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("-InstallIfMissing", launcher)
        self.assertIn("Get-WebView2RuntimeVersion", prepare_script)
        self.assertIn('Start-Process -FilePath $resolvedOutputPath', prepare_script)

    def test_ci_build_prepares_bootstrapper_for_each_architecture(self):
        """确认 x86 和 x64 CI 构建都会生成包含 Bootstrapper 的安装包。"""
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "build-windows-exe.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("prepare-webview2-bootstrapper.ps1", workflow)
        self.assertIn("/DWebView2Bootstrapper=", workflow)

    def test_mpremote_firmware_updater_is_bundled(self):
        """确认发布版包含 mpremote 模块和流式复制脚本。"""
        specification = (MONITOR_ROOT / "pico_monitor.spec").read_text(
            encoding="utf-8"
        )
        requirements = (MONITOR_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn('collect_submodules("mpremote")', specification)
        self.assertIn("mpremote_stream_copy.py", specification)
        self.assertIn("mpremote>=", requirements)

    def test_device_page_exposes_port_package_and_full_update_mode(self):
        """确认设备管理固件更新可选择串口、ZIP 包和全量覆盖模式。"""
        page = (
            MONITOR_ROOT / "win" / "ui-web" / "src" / "components"
            / "DevicePage.vue"
        ).read_text(encoding="utf-8")
        bridge = (
            MONITOR_ROOT / "win" / "ui-web-api" / "bridge.py"
        ).read_text(encoding="utf-8")

        self.assertIn("device.firmware.select", page)
        self.assertIn("device.firmware.ports", page)
        self.assertIn("v-model=\"firmware.force\"", page)
        self.assertIn("packagePath: firmware.package.path", page)
        self.assertIn('"device.firmware.select"', bridge)
        self.assertIn('"device.firmware.ports"', bridge)

    def test_full_firmware_update_forwards_mpremote_force_flag(self):
        """确认全量更新会向 mpremote 复制进程追加 force 参数。"""
        tray = (MONITOR_ROOT / "win" / "tray.py").read_text(encoding="utf-8")
        device_api = (
            MONITOR_ROOT / "win" / "ui-web-api" / "device_api.py"
        ).read_text(encoding="utf-8")

        self.assertIn('command.append("--force")', tray)
        self.assertIn("force=force", device_api)

    def test_all_web_log_views_use_copyable_log_component(self):
        """确认全部 Web 日志滚动框统一提供悬浮复制完整内容的能力。"""
        component_root = MONITOR_ROOT / "win" / "ui-web" / "src" / "components"
        copyable_log = (component_root / "CopyableLog.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn("navigator.clipboard.writeText(props.content)", copyable_log)
        self.assertIn('aria-label="复制全部日志"', copyable_log)
        for component_name in (
            "CustomDataPage.vue",
            "DevicePage.vue",
            "GlobalLoadingOverlay.vue",
            "LogsPage.vue",
            "UpdatePage.vue",
        ):
            with self.subTest(component=component_name):
                component = (component_root / component_name).read_text(
                    encoding="utf-8"
                )
                self.assertIn("<CopyableLog", component)
