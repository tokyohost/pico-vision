"""验证驱动语言配置、展示翻译和传输兼容性。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
from unittest import mock

from i18n import CHINESE, ENGLISH, error_response, set_locale, t
from desktop.common.settings import DEFAULT_SETTINGS, TraySettingsStore, apply_worker_arguments, style_label
from desktop.common.ui_api.bridge import WebViewBridge
from desktop.common.ui_api.webview import WebUiMixin
from desktop.linux.bridge import LinuxInvokeBridge
from monitor_core.arguments import create_argument_parser
from monitor_core.runtime_operations import RuntimeOperationsMixin
from monitor_core.style_commands import StyleCommandMixin
from pico_snapshot import build_snapshot_packets, snapshot_envelope_payload


class I18nTest(unittest.TestCase):
    """覆盖双语资源、配置保存及热更新的关键行为。"""

    def tearDown(self):
        """恢复全局语言，避免影响其他兼容测试。"""
        set_locale("zh-CN")

    def test_catalog_keys_and_placeholders_match(self):
        """每个语言包的键和占位符保持一致。"""
        self.assertEqual(set(CHINESE), set(ENGLISH))
        for key in CHINESE:
            chinese = [field for _, field, _, _ in Formatter().parse(CHINESE[key]) if field is not None]
            english = [field for _, field, _, _ in Formatter().parse(ENGLISH[key]) if field is not None]
            self.assertEqual(sorted(chinese), sorted(english), key)

    def test_lookup_fallback_and_named_parameters(self):
        """未知键安全回退，命名参数可在两种语言中重排。"""
        set_locale("en-US")
        self.assertEqual("Language", t("common.language"))
        self.assertEqual("missing.key", t("missing.key"))
        with mock.patch.dict(CHINESE, {"test.named": "你好 {name}"}), mock.patch.dict(ENGLISH, {"test.named": "Hello {name}"}):
            self.assertEqual("Hello Ada", t("test.named", {"name": "Ada"}))
        with mock.patch.dict(CHINESE, {"test.fallback": "回退"}):
            self.assertEqual("回退", t("test.fallback"))

    def test_native_window_titles_use_plain_strings(self):
        """启动和切换语言均向原生窗口传普通字符串，避免 pythonnet 转换失败。"""
        for locale in ("zh-CN", "en-US"):
            with self.subTest(locale=locale):
                set_locale(locale)
                application = mock.MagicMock()
                application._resource_path.return_value = Path(__file__)
                application.settings = dict(DEFAULT_SETTINGS)
                webview = mock.MagicMock()
                with mock.patch.dict(sys.modules, {"webview": webview}):
                    WebUiMixin._initialize_webview(application)
                title = webview.create_window.call_args.args[0]
                self.assertIs(type(title), str)
                self.assertEqual(t("message.control_center").format("OmniWatch"), title)

                bridge = WebViewBridge(application)
                bridge._save_settings({"settings": {"locale": locale}})
                updated_title = application.webview_window.set_title.call_args.args[0]
                self.assertIs(type(updated_title), str)
                self.assertEqual(title, updated_title)

    def test_settings_cli_and_yaml_round_trip(self):
        """旧配置默认中文，保存后传递给命令行及 YAML 解析器。"""
        with tempfile.TemporaryDirectory() as directory:
            store = TraySettingsStore(Path(directory) / "settings.json")
            settings = store.load()
            self.assertEqual("zh-CN", settings["locale"])
            settings["locale"] = "en-US"
            store.save(settings)
            self.assertEqual("en-US", store.load()["locale"])
            argv = apply_worker_arguments([], settings)
            args = create_argument_parser().parse_args(argv)
            self.assertEqual("en-US", args.locale)
            settings["locale"] = "invalid"
            store.save(settings)
            self.assertEqual("zh-CN", store.load()["locale"])
        args = create_argument_parser({"screen": {"locale": "en-US"}}).parse_args([])
        self.assertEqual("en-US", args.locale)

    def test_runtime_locale_is_added_to_existing_display_snapshot(self):
        """热更新只增加显示字段，不改变快照信封和分片协议。"""
        arguments = create_argument_parser().parse_args([])
        service = SimpleNamespace(arguments=arguments, available_styles={arguments.lcd_style},
                                  available_idle_styles={"idle"}, _effective_transmit_interval=lambda: 0.5)
        StyleCommandMixin.apply_display_config(service, {"locale": "en-US"})
        display = RuntimeOperationsMixin._display_configuration_snapshot(service)
        self.assertEqual("en-US", display["locale"])
        self.assertEqual(arguments.lcd_style, display["style"])
        envelope = json.loads(snapshot_envelope_payload({"display": display}))
        self.assertEqual("snapshot", envelope["mode"])
        self.assertEqual(display, envelope["data"]["display"])
        self.assertTrue(build_snapshot_packets({"display": display}))
        with self.assertRaises(ValueError):
            StyleCommandMixin.apply_display_config(service, {"locale": "invalid"})
        self.assertEqual("en-US", arguments.locale)

    def test_theme_names_do_not_follow_locale(self):
        """内置及自定义主题名称均保留原始元数据。"""
        settings = dict(DEFAULT_SETTINGS, locale="en-US")
        self.assertIn("经典概览", style_label("default", settings))
        settings["styles"] = [{"name": "default", "chinese_name": "作者名称", "type": "custom"}]
        self.assertIn("作者名称", style_label("default", settings))

    def test_bridge_uses_locale_and_preserves_external_error_details(self):
        """用户提示使用当前语言，第三方异常详情不丢失。"""
        app = SimpleNamespace(settings={"locale": "en-US"})
        result = WebViewBridge(app).invoke("system.copyText", {"text": None})
        self.assertFalse(result["ok"])
        self.assertIn("Clipboard", result["message"])
        result = error_response(RuntimeError("第三方失败"))
        self.assertEqual("第三方失败", result["details"])
        self.assertIn("Operation failed", result["message"])

    def test_style_validation_errors_keep_specific_english_message(self):
        """内置校验错误保留具体英文原因，不退化为第三方通用错误。"""
        from style_validator import StyleFileValidator
        set_locale("en-US")
        with self.assertRaises(ValueError) as captured:
            StyleFileValidator().validate("style_demo.txt")
        result = error_response(captured.exception)
        self.assertIn(".py", result["message"])
        self.assertNotIn("details", result)

    def test_file_conflict_code_is_independent_of_language(self):
        """覆盖确认使用错误类型，不依赖中文或英文消息匹配。"""
        for locale in ("zh-CN", "en-US"):
            set_locale(locale)
            error = FileExistsError(t('message.style_and_file_already_exist_in_omniwatch').format("demo", "style_demo.py"))
            result = error_response(error)
            self.assertEqual("file_exists", result["code"])
            self.assertIn("demo", result["message"])
            self.assertNotIn("code", error_response(RuntimeError("other")))

    def test_linux_http_persists_same_language_field(self):
        """Linux 管理页沿用 screen.locale，写回配置且不增加独立语言来源。"""
        import yaml
        arguments = create_argument_parser().parse_args([])
        service = SimpleNamespace(arguments=arguments)
        bridge = LinuxInvokeBridge(service)
        with tempfile.TemporaryDirectory() as directory:
            arguments.config = str(Path(directory) / "monitor.yml")
            Path(arguments.config).write_text("{}", encoding="utf-8")
            arguments.locale = "en-US"
            with mock.patch.object(bridge, "_style_catalog", return_value=[]):
                self.assertTrue(bridge._save_linux_settings())
            payload = yaml.safe_load(Path(arguments.config).read_text(encoding="utf-8"))
            self.assertEqual("en-US", payload["screen"]["locale"])


if __name__ == "__main__":
    unittest.main()
