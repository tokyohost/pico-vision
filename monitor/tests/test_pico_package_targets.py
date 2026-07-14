"""验证 RP2040 与 ESP32-S3 升级包的板型专属内容。"""


import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "picoRP2040"
PACKAGER_PATH = PROJECT_ROOT / "tools" / "package_pico_upgrade.py"
SPEC = importlib.util.spec_from_file_location("package_pico_upgrade", PACKAGER_PATH)
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


class PicoPackageTargetsTest(unittest.TestCase):
    """确认不同开发板升级包启用正确功能并避免携带无用资源。"""

    def _build(self, directory, board_model):
        """为指定开发板生成二英寸屏测试升级包。"""
        output = Path(directory) / (board_model + ".zip")
        PACKAGER.build_package(
            SOURCE_ROOT,
            output,
            "test",
            board_model,
            "st7789-2inch-8pin-a",
        )
        return output

    def test_esp32_package_enables_wireless_and_contains_font(self):
        """ESP32-S3 包应启用 Wi-Fi，并包含 WebSocket 与中文字库。"""
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(self._build(directory, "esp32-s3")) as archive:
                names = set(archive.namelist())
                config = archive.read("config.py").decode("utf-8")
        self.assertIn('BOARD_MODEL = "esp32-s3"', config)
        self.assertIn("WIFI_ENABLED = True", config)
        self.assertIn("net/wifi.py", names)
        self.assertIn("net/websocket.py", names)
        self.assertIn("fonts/fusion_pixel_8px_zh_hans.fpf", names)
        self.assertIn("styles/style_fusion_pixel_test.py", names)

    def test_rp2040_package_disables_wireless_and_omits_esp32_resources(self):
        """RP2040 包应关闭无线功能并排除 ESP32 专属资源。"""
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(self._build(directory, "rp2040_usb")) as archive:
                names = set(archive.namelist())
                config = archive.read("config.py").decode("utf-8")
        self.assertIn('BOARD_MODEL = "rp2040_usb"', config)
        self.assertIn("WIFI_ENABLED = False", config)
        self.assertNotIn("net/wifi.py", names)
        self.assertNotIn("net/websocket.py", names)
        self.assertNotIn("font_fusion_pixel.py", names)
        self.assertIn("styles/style_fusion_pixel_test.py", names)
        self.assertFalse(any(name.startswith("fonts/") for name in names))


if __name__ == "__main__":
    unittest.main()
