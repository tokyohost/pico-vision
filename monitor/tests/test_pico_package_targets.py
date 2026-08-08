"""验证独立维护的 ESP32-S3 源码能够完整生成设备固件包。"""


import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "esp32-s3"
PACKAGER_PATH = PROJECT_ROOT / "tools" / "package_pico_firmware.py"
SPEC = importlib.util.spec_from_file_location("package_pico_firmware", PACKAGER_PATH)
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


class PicoPackageTargetsTest(unittest.TestCase):
    """确认发布包与 ESP32-S3 本地部署内容保持一致。"""

    def _build(self, directory, board_model):
        """为指定开发板生成十针二点四英寸屏测试全量固件包。"""
        output = Path(directory) / (board_model + ".zip")
        PACKAGER.build_package(
            SOURCE_ROOT,
            output,
            "test",
            board_model,
            "st7789-2.4inch-10pin-a",
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
        self.assertIn("render_service.py", names)
        self.assertIn("net/websocket_clients.py", names)
        self.assertIn("usb/native_cdc.py", names)
        self.assertFalse(any(name.startswith("fonts/") for name in names))
        self.assertNotIn("manifest.json", names)


if __name__ == "__main__":
    unittest.main()
