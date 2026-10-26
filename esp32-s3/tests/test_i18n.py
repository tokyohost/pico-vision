"""验证设备语言持久化、菜单翻译和帧边界更新。"""

import json
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from unittest import mock

import i18n
from main import Application
from menu import SystemMenu
from screen_text import CHINESE_FONT, draw_text, text_width, fit_text
from styles.style_idle import IdleStyle


class DeviceI18nTest(unittest.TestCase):
    """使用临时存储覆盖重启、异常和反复快照场景。"""

    def setUp(self):
        """为每项测试准备独立的语言文件。"""
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "locale.json")
        i18n.load_locale(self.path)

    def tearDown(self):
        """恢复默认语言并清理临时文件。"""
        self.directory.cleanup()
        i18n.load_locale(self.path)

    def test_locale_survives_restart_and_only_writes_on_change(self):
        """语言变化只写一次，重启继续显示已选语言。"""
        with mock.patch.object(i18n.os, "rename", wraps=i18n.os.rename) as rename:
            self.assertTrue(i18n.set_locale("en-US"))
            for _ in range(100):
                self.assertFalse(i18n.set_locale("en-US"))
            self.assertEqual(1, rename.call_count)
        self.assertEqual("en-US", i18n.load_locale(self.path))
        self.assertEqual("System menu", i18n.t("menu.title"))
        self.assertEqual({"locale": "en-US"}, json.loads(Path(self.path).read_text()))

    def test_invalid_missing_and_corrupt_values_are_safe(self):
        """非法快照不覆盖当前语言，损坏持久化文件默认中文。"""
        i18n.set_locale("en-US")
        for value in (None, "", "invalid", {}, []):
            self.assertFalse(i18n.set_locale(value))
        self.assertEqual("en-US", i18n.get_locale())
        Path(self.path).write_text("broken", encoding="utf-8")
        self.assertEqual("zh-CN", i18n.load_locale(self.path))

    def test_write_failure_keeps_runtime_and_previous_file(self):
        """写入失败不阻断会话，也不删除旧配置。"""
        Path(self.path).write_text('{"locale":"zh-CN"}', encoding="utf-8")
        with mock.patch.object(i18n.os, "rename", side_effect=OSError("disk full")):
            self.assertTrue(i18n.set_locale("en-US"))
        self.assertEqual("en-US", i18n.get_locale())
        self.assertEqual("zh-CN", json.loads(Path(self.path).read_text())["locale"])

    def test_menu_translates_but_theme_weekday_stays_original(self):
        """系统菜单随语言切换，主题星期文案保持原样。"""
        menu = SystemMenu()
        menu.open()
        self.assertEqual("系统菜单", menu.view()["title"])
        i18n.set_locale("en-US")
        menu.open()
        self.assertEqual("System menu", menu.view()["title"])
        self.assertEqual("Back", menu.view()["items"][-1][1])
        self.assertEqual("星期六", IdleStyle._weekday(2026, 10, 24))

    def test_language_application_aborts_old_frame_and_clears_hints(self):
        """帧边界切换时撤销旧帧，增量缺失字段不会重置语言。"""
        app = Application.__new__(Application)
        app._renderer = mock.Mock()
        app._rendering_version = 20
        app._button_hint_label = "旧提示"
        self.assertTrue(app._apply_display_locale({"display": {"locale": "en-US"}}))
        app._renderer.abort_render.assert_called_once_with(release_snapshot=True)
        self.assertEqual(-1, app._rendering_version)
        self.assertIsNone(app._button_hint_label)
        self.assertFalse(app._apply_display_locale({"display": {"brightness": 30}}))
        self.assertFalse(app._apply_display_locale({"display": {"locale": "en-US"}}))
        app._renderer.abort_render.assert_called_once()

    def test_menu_defers_remote_language_until_exit(self):
        """远端语言在菜单期间不生效，退出后采用最新快照。"""
        from test_monitor_waiting_page import MonitorWaitingPageTest
        harness = MonitorWaitingPageTest()
        app, state = harness.create_application(idle_enabled=False, receiver_busy=True)
        app._cache.snapshot["display"]["locale"] = "en-US"
        app._system_menu = SystemMenu()
        app._system_menu.open()
        harness.run_application(app, state)
        self.assertEqual("zh-CN", i18n.get_locale())
        app._monitor_timed_out = mock.Mock(return_value=False)
        with mock.patch("main.time.ticks_ms", return_value=6000, create=True), \
                mock.patch("main.time.ticks_diff", side_effect=lambda a, b: a - b, create=True):
            app._close_system_menu()
        self.assertEqual("en-US", i18n.get_locale())

    def test_fixed_width_clipping_and_chinese_character_coverage(self):
        """中英文按字宽裁剪，新增中文文案仅使用已有 GB2312 字形。"""
        canvas = mock.Mock()
        canvas.text_width.side_effect = lambda value, scale=1, **kwargs: sum(
            16 if ord(char) > 127 else 8 for char in value) * scale
        self.assertEqual("中A", fit_text(canvas, "中AB", 24))
        self.assertEqual("ABC", fit_text(canvas, "ABCD", 24))
        for value in i18n.CHINESE.values():
            for char in value:
                if "\u3400" <= char <= "\u9fff":
                    char.encode("gb2312")

    def test_legacy_main_ignores_new_display_field(self):
        """未接入国际化的旧主循环应忽略新增字段并正常继续绘制。"""
        import subprocess
        import sys
        root = Path(__file__).resolve().parents[2]
        # 独立进程防止新旧固件的同名 config、main 和 styles 模块互相污染。
        code = """
import sys
from pathlib import Path
from unittest.mock import Mock
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'picoRP2040'))
sys.path.insert(0, str(root / 'esp32-s3/tests'))
import main
from test_monitor_waiting_page import MonitorWaitingPageTest
harness = MonitorWaitingPageTest()
app, state = harness.create_application(idle_enabled=False, fresh_message=True)
app._cache.snapshot['display']['locale'] = 'en-US'
app._lcd = Mock()
app._lcd.set_backlight_brightness.return_value = False
harness.run_application(app, state)
assert state['style'] == 'default'
assert app._renderer.request_render.call_count > 0
"""
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(root)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_catalog_and_font_selection(self):
        """语言键及占位符一致，中文测量和绘制选用相同字体。"""
        self.assertEqual(set(i18n.CHINESE), set(i18n.ENGLISH))
        for key in i18n.CHINESE:
            fields = lambda text: sorted(field for _, field, _, _ in Formatter().parse(text) if field is not None)
            self.assertEqual(fields(i18n.CHINESE[key]), fields(i18n.ENGLISH[key]), key)
        canvas = mock.Mock()
        draw_text(canvas, 0, 0, "磁盘总览", 1)
        text_width(canvas, "磁盘总览")
        self.assertEqual(CHINESE_FONT, canvas.text.call_args.kwargs["font_name"])
        self.assertEqual(CHINESE_FONT, canvas.text_width.call_args.kwargs["font_name"])
        draw_text(canvas, 0, 0, "CPU", 1)
        self.assertEqual({}, canvas.text.call_args.kwargs)
        self.assertEqual("missing.key", i18n.t("missing.key"))


if __name__ == "__main__":
    unittest.main()
