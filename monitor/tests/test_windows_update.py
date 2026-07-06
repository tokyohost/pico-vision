"""验证 Windows GitHub Release 更新资源选择行为。"""

import unittest
from unittest import mock

from windows_update import WindowsReleaseUpdater


class WindowsReleaseUpdaterTest(unittest.TestCase):
    """验证 Windows Monitor 与 Pico 联合更新器。"""

    def test_latest_release_returns_version_and_assets(self):
        """确认 latest 标签会移除版本号前缀。"""
        updater = WindowsReleaseUpdater("owner/repository", "1.0.0")
        assets = [{"name": "asset"}]
        with mock.patch.object(
            updater,
            "_request_json",
            return_value={"tag_name": "v1.1.0", "assets": assets},
        ):
            self.assertEqual(("1.1.0", assets), updater.latest_release("https://updates.example/latest"))

    def test_selects_matching_windows_and_pico_assets(self):
        """确认按进程位数和版本选择两个更新资源。"""
        assets = [
            {"name": "pico-monitor-windows-x64.exe"},
            {"name": "pico-upgrade-v1.1.0.zip"},
        ]
        updater = WindowsReleaseUpdater("owner/repository", "1.0.0")
        with mock.patch("windows_update.platform.architecture", return_value=("64bit", "WindowsPE")):
            self.assertEqual(
                "pico-monitor-windows-x64.exe",
                updater.select_monitor_asset(assets)["name"],
            )
        self.assertEqual(
            "pico-upgrade-v1.1.0.zip",
            updater.select_pico_asset(assets, "1.1.0")["name"],
        )

    def test_missing_update_url_is_rejected(self):
        """确认没有默认仓库和自定义地址时给出配置错误。"""
        updater = WindowsReleaseUpdater("", "development")
        with self.assertRaisesRegex(RuntimeError, "未配置更新地址"):
            updater.latest_release()


if __name__ == "__main__":
    unittest.main()
