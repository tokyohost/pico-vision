"""验证独立维护的 ESP32-S3 源码能够完整生成设备固件包。"""


import hashlib
import importlib.util
import io
import re
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "esp32-s3"
PACKAGER_PATH = PROJECT_ROOT / "tools" / "package_pico_firmware.py"
SPEC = importlib.util.spec_from_file_location("package_pico_firmware", PACKAGER_PATH)
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


class PicoPackageTargetsTest(unittest.TestCase):
    """确认发布包与 ESP32-S3 本地部署内容保持一致。"""

    def _build(self, directory, board_model, lcd_device_type="st7789-2.4inch-10pin-a"):
        """为指定开发板和屏幕生成测试全量固件包，默认保留十针 A 款。"""
        output = Path(directory) / (board_model + ".zip")
        PACKAGER.build_package(
            SOURCE_ROOT,
            output,
            "test",
            board_model,
            lcd_device_type,
        )
        return output

    def test_esp32_package_matches_maintained_source(self):
        """除测试和内置字体资料外，ESP32-S3 发布包不得遗漏源码文件。"""
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(self._build(directory, "esp32-s3")) as archive:
                names = set(archive.namelist())
                config = archive.read("config.py").decode("utf-8")
        expected = {
            path.relative_to(SOURCE_ROOT).as_posix()
            for path in SOURCE_ROOT.rglob("*")
            if (
                path.is_file()
                and path.suffix.lower() in (".py", ".txt")
                and "tests" not in tuple(part.lower() for part in path.relative_to(SOURCE_ROOT).parts)
                and "__pycache__" not in tuple(part.lower() for part in path.relative_to(SOURCE_ROOT).parts)
                and not path.relative_to(SOURCE_ROOT).as_posix().startswith("fonts/")
            )
        }
        self.assertIn('BOARD_MODEL = "esp32-s3"', config)
        self.assertIn("WIFI_ENABLED = True", config)
        self.assertEqual(expected, names)
        self.assertIn("device_identity.py", names)
        self.assertTrue({"i18n.py", "screen_text.py", "locales/__init__.py",
                         "locales/zh_cn.py", "locales/en_us.py"}.issubset(names))
        self.assertNotIn("locale.json", names)
        self.assertIn("render_service.py", names)
        self.assertIn("net/websocket_clients.py", names)
        self.assertIn("usb/native_cdc.py", names)
        self.assertFalse(any(name.startswith("fonts/") for name in names))
        self.assertNotIn("manifest.json", names)


    def test_actions_matrix_includes_all_supported_panels(self):
        """Actions 应覆盖四种屏幕，默认兼容包仍取自十针 A 款。"""
        board_models, lcd_types = PACKAGER.load_supported_targets(SOURCE_ROOT)
        self.assertEqual(board_models, ("esp32-s3",))
        self.assertEqual(set(lcd_types), {
            "st7789-2inch-8pin-a", "st7789-2.4inch-8pin-b",
            "st7789-2.4inch-10pin-a", "st7789-2.4inch-10pin-backpcb",
        })
        workflow = (PROJECT_ROOT / ".github/workflows/build-pico-firmware.yml").read_text(
            encoding="utf-8"
        )
        matrix = workflow.split("        lcd_device_type:\n", 1)[1].split(
            "    steps:", 1
        )[0]
        self.assertEqual(
            set(re.findall(r"(?m)^          - ([a-z0-9.-]+)$", matrix)),
            set(lcd_types),
        )
        self.assertIn(
            'source="release-assets/OmniWatch-pico-full-v${version}'
            '-esp32-s3-st7789-2.4inch-10pin-a.zip"', workflow
        )

    def test_packages_load_panel_specific_button_defaults(self):
        """四种方案及背板别名的包配置应在加载时得到对应按键引脚。"""
        targets = (
            ("st7789-2inch-8pin-a", 3),
            ("st7789-2.4inch-8pin-b", 3),
            ("st7789-2.4inch-10pin-a", 3),
            ("st7789-2.4inch-10pin-backpcb", 42),
            ("st7789_2_4inch_10pin_backpcb", 42),
        )
        with tempfile.TemporaryDirectory() as directory:
            for device_type, function_pin in targets:
                with self.subTest(device_type=device_type):
                    output = self._build(directory, "esp32-s3", device_type)
                    with zipfile.ZipFile(output) as archive:
                        self.assertIsNone(archive.testzip())
                        config = archive.read("config.py").decode("utf-8")
                        module = "lcd/st7789_2_4inch_10pin_backpcb.py"
                        self.assertEqual(
                            archive.read(module), (SOURCE_ROOT / module).read_bytes()
                        )
                    configuration = {}
                    with mock.patch("builtins.open", side_effect=FileNotFoundError):
                        exec(compile(config, "config.py", "exec"), configuration)
                    self.assertEqual(
                        (configuration["PIN_BUTTON_STYLE_PREVIOUS"],
                         configuration["PIN_BUTTON_STYLE_NEXT"],
                         configuration["PIN_BUTTON_FUNCTION"]),
                        (1, 2, function_pin),
                    )
                    self.assertEqual(configuration["FIRMWARE_VERSION"], "test")
                    self.assertTrue(configuration["BUTTON_ACTIVE_LOW"])
                    self.assertEqual(
                        configuration["LCD_DEVICE_TYPE"],
                        "st7789-2.4inch-10pin-backpcb" if function_pin == 42 else device_type,
                    )

    def test_backpcb_cli_creates_zip_and_matching_sha256(self):
        """与 Actions 相同的命令行入口应生成背板 ZIP 和可核对的摘要文件。"""
        original_config = (SOURCE_ROOT / "config.py").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / (
                "OmniWatch-pico-full-vtest-esp32-s3-st7789-2.4inch-10pin-backpcb.zip"
            )
            arguments = [
                str(PACKAGER_PATH), "--source", str(SOURCE_ROOT),
                "--output", str(output), "--version", "test",
                "--board-model", "esp32-s3",
                "--lcd-device-type", "st7789-2.4inch-10pin-backpcb",
            ]
            with mock.patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()):
                PACKAGER.main()
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(
                output.with_suffix(".zip.sha256").read_text(encoding="utf-8"),
                "{}  {}\n".format(digest, output.name),
            )
        self.assertEqual((SOURCE_ROOT / "config.py").read_bytes(), original_config)


if __name__ == "__main__":
    unittest.main()
