#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



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
        package_name = "OmniWatch_1.2.4_amd64.deb"
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

    def test_http_progress_callback_receives_download_and_install_stages(self):
        """确认 Linux HTTP 调用方能取得 DEB 下载百分比和 APT 安装阶段。"""
        package_name = "OmniWatch_1.2.4_amd64.deb"
        assets = [
            {"name": package_name, "browser_download_url": "https://example/deb"},
        ]
        progress = []
        updater = LinuxDebUpdater("owner/repository", "1.2.3")

        def download(asset, progress_callback=None):
            """模拟下载资源，并主动回调一半和全部字节进度。"""
            temporary = tempfile.NamedTemporaryFile(delete=False)
            temporary.write(b"deb-package")
            temporary.close()
            if progress_callback is not None:
                progress_callback(50, 100)
                progress_callback(100, 100)
            return temporary.name

        with mock.patch.object(updater, "_validate_environment"):
            with mock.patch.object(
                updater,
                "_request_json",
                return_value={"tag_name": "v1.2.4", "assets": assets},
            ):
                with mock.patch.object(updater, "_architecture", return_value="amd64"):
                    with mock.patch.object(updater, "_download", side_effect=download):
                        with mock.patch("monitor_update.subprocess.run"):
                            self.assertTrue(
                                updater.update(
                                    progress_callback=lambda message, percent: progress.append(
                                        (message, percent)
                                    )
                                )
                            )

        self.assertIn(("正在下载 Linux DEB：50%（50.0 B / 100.0 B）", 40), progress)
        self.assertTrue(any("正在通过 APT 安装" in item[0] for item in progress))
        self.assertEqual(100, progress[-1][1])


if __name__ == "__main__":
    unittest.main()
