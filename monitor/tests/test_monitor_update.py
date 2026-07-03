"""验证 Linux DEB 自动更新的发布资源选择、摘要校验与安装流程。"""

import hashlib
import pathlib
import tempfile
import unittest
from unittest import mock

import monitor_update
from monitor_update import CHECKSUM_ASSET_NAME, LinuxDebUpdater


class LinuxDebUpdaterTests(unittest.TestCase):
    """覆盖 Linux DEB 自动更新的关键安全行为。"""

    def test_current_version_skips_installation(self):
        """确认当前版本等于最新 Release 时不会下载或安装。"""
        updater = LinuxDebUpdater("owner/repository", "1.2.3")
        with mock.patch.object(updater, "_validate_environment"):
            with mock.patch.object(updater, "_request_json", return_value={"tag_name": "v1.2.3"}):
                with mock.patch.object(updater, "_download") as download:
                    self.assertFalse(updater.update())
        download.assert_not_called()

    def test_downloads_matching_package_and_installs_with_apt(self):
        """确认更新器选择当前架构 DEB、校验摘要并交给 APT 安装。"""
        package_name = "pico-monitor_1.2.4_amd64.deb"
        assets = [
            {"name": package_name, "browser_download_url": "https://example/deb"},
            {"name": CHECKSUM_ASSET_NAME, "browser_download_url": "https://example/sums"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            package_path = pathlib.Path(directory) / package_name
            package_path.write_bytes(b"deb-package")
            digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
            checksum_path = pathlib.Path(directory) / CHECKSUM_ASSET_NAME
            checksum_path.write_text("{}  ./{}\n".format(digest, package_name), encoding="utf-8")
            updater = LinuxDebUpdater("owner/repository", "1.2.3")
            with mock.patch.object(updater, "_validate_environment"):
                with mock.patch.object(updater, "_request_json", return_value={"tag_name": "v1.2.4", "assets": assets}):
                    with mock.patch.object(updater, "_architecture", return_value="amd64"):
                        with mock.patch.object(updater, "_download", side_effect=(str(package_path), str(checksum_path))):
                            with mock.patch("monitor_update.subprocess.run") as process_runner:
                                self.assertTrue(updater.update())

        process_runner.assert_called_once_with(
            ["apt-get", "install", "--yes", str(package_path)],
            check=True,
        )

    def test_requires_root_on_linux(self):
        """确认普通用户无法直接触发系统 DEB 安装。"""
        updater = LinuxDebUpdater("owner/repository", "1.2.3")
        with mock.patch.object(monitor_update.sys, "platform", "linux"):
            with mock.patch.object(monitor_update.os, "geteuid", return_value=1000, create=True):
                with self.assertRaisesRegex(RuntimeError, "root 权限"):
                    updater._validate_environment()


if __name__ == "__main__":
    unittest.main()
