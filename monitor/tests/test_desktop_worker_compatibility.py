"""验证设备握手后的公共配置同步和远程注册 API 地址选择。"""

import ast
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from desktop.common.settings import TraySettingsStore
from desktop.common.ui_api.device_api import DeviceApiMixin
from monitor_core.style_commands import StyleCommandMixin


class RegistrationApiHarness(DeviceApiMixin):
    """为无状态接口混入类提供测试所需的应用属性。"""


class DesktopWorkerCompatibilityTest(unittest.TestCase):
    """覆盖源码测试原先没有触发的桌面环境变量和冻结包分支。"""

    def test_style_catalog_updates_shared_settings_without_windows_import(self):
        """桌面 worker 在握手后将样式写入公共配置，不依赖 Windows 兼容模块。"""
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            service = StyleCommandMixin()
            service.client = SimpleNamespace(styles=[{
                "name": "custom_test", "chinese_name": "测试样式", "type": "custom"}])
            service.arguments = SimpleNamespace(lcd_style="horizontal_disk6x", idle_style="idle")
            with mock.patch.dict(os.environ, {"PICO_MONITOR_SETTINGS_PATH": str(settings_path)}):
                service._synchronize_style_catalog()
            self.assertTrue(settings_path.is_file())
            styles = TraySettingsStore(settings_path).load()["styles"]
            self.assertTrue(any(style["name"] == "custom_test" for style in styles))
            # AST 检查涵盖函数内延迟导入，防止源码能运行而 Mac 冻结包再次漏依赖。
            source = Path(__file__).resolve().parents[1] / "monitor_core/style_commands.py"
            windows_imports = [node.module for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                               if isinstance(node, ast.ImportFrom) and node.module
                               and (node.module == "win" or node.module.startswith("win."))]
            self.assertEqual(windows_imports, [])

    def test_registration_prefix_respects_server_location_and_explicit_path(self):
        """开发桌面连接远程市场使用正式代理，本机开发与用户明确路径保持兼容。"""
        api = RegistrationApiHarness()
        for version in ("development", "1.2.3"):
            for url, expected in (
                ("https://omni.mzlblog.com", "https://omni.mzlblog.com/prod-api"),
                ("https://example.test/market", "https://example.test/prod-api"),
                ("https://example.test/custom-api/market", "https://example.test/custom-api"),
                ("http://localhost:5173", "http://localhost:5173/" +
                 ("dev-api" if version == "development" else "prod-api")),
            ):
                with self.subTest(version=version, url=url), mock.patch(
                        "desktop.common.ui_api.device_api.MONITOR_VERSION", version):
                    api._application = SimpleNamespace(settings={"market_url": url})
                    self.assertEqual(api._registration_api_base(), expected)

    def test_registration_invalid_html_is_not_reported_as_registered(self):
        """服务器误返 HTML 时仍明确报错，不隐藏注册失败或伪造注册成功。"""
        with self.assertRaisesRegex(RuntimeError, "注册服务返回了无效响应"):
            DeviceApiMixin._read_registration_response(io.BytesIO(b"<html></html>"))
        result = DeviceApiMixin._read_registration_response(io.BytesIO(json.dumps(
            {"code": 200, "registered": False}).encode("utf-8")))
        self.assertFalse(result["registered"])


if __name__ == "__main__":
    unittest.main()
