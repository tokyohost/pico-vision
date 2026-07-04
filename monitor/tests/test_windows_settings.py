"""验证 Windows 设置持久化与参数转换，不依赖实际托盘环境。"""

import json
import tempfile
import unittest
from pathlib import Path

from windows_settings import DEFAULT_SETTINGS, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def test_missing_file_uses_complete_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json").load()
        self.assertEqual(settings, DEFAULT_SETTINGS)

    def test_unknown_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"interval": 1.5, "unknown": True}), encoding="utf-8")
            settings = SettingsStore(path).load()
        self.assertEqual(settings["interval"], 1.5)
        self.assertNotIn("unknown", settings)

    def test_worker_arguments_include_every_runtime_setting(self):
        settings = dict(DEFAULT_SETTINGS)
        settings.update({
            "port": "COM8",
            "screen_rotation": 180,
            "network_unit": "Mbps",
            "lcd_style": "simple",
            "qbittorrent_enabled": True,
            "qbittorrent_address": "http://localhost:8080",
            "qbittorrent_username": "admin",
            "qbittorrent_password": "secret",
        })
        arguments = SettingsStore.worker_arguments(settings)
        self.assertIn("--qbittorrent-enabled", arguments)
        for option in (
            "--port", "--ping-target", "--interval", "--reconnect-interval",
            "--screen-rotation", "--network-unit", "--lcd-style",
            "--qbittorrent-address", "--qbittorrent-username",
            "--qbittorrent-password", "--qbittorrent-interval",
        ):
            self.assertIn(option, arguments)


if __name__ == "__main__":
    unittest.main()
