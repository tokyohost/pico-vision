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



"""从 GitHub Release 下载并安装最新的 Linux DEB 软件包。"""


import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request


LOGGER = logging.getLogger("pico-monitor.update")
CHECKSUM_ASSET_NAME = "OmniWatch-SHA256SUMS-linux-deb.txt"


class LinuxDebUpdater:
    """发现与当前架构匹配的最新 DEB，并通过 APT 完成更新。"""

    def __init__(self, repository, current_version):
        """保存 GitHub 仓库名称和当前 Monitor 版本。"""
        self.repository = str(repository or "").strip()
        self.current_version = str(current_version or "").strip()

    def update(self):
        """检查运行环境、下载最新 DEB、校验摘要并调用 APT 安装。"""
        self._validate_environment()
        release = self._request_json(
            "https://api.github.com/repos/{}/releases/latest".format(
                self.repository
            )
        )
        latest_version = str(release.get("tag_name") or "").lstrip("v")
        if not latest_version:
            raise RuntimeError("GitHub 最新 Release 缺少版本标签")
        if latest_version == self.current_version:
            LOGGER.info("当前已是最新版本：%s", self.current_version)
            return False

        architecture = self._architecture()
        assets = release.get("assets") or []
        package_asset = self._find_package_asset(assets, architecture)
        checksum_asset = self._find_asset(assets, CHECKSUM_ASSET_NAME)
        LOGGER.info(
            "发现新版本：当前=%s，最新=%s，架构=%s",
            self.current_version,
            latest_version,
            architecture,
        )
        package_path = self._download(package_asset)
        try:
            if checksum_asset is not None:
                checksum_path = self._download(checksum_asset)
                try:
                    self._verify_checksum(
                        package_path,
                        package_asset["name"],
                        checksum_path,
                    )
                finally:
                    self._remove_file(checksum_path)
            else:
                LOGGER.warning("Release 未提供 %s，跳过独立摘要校验", CHECKSUM_ASSET_NAME)
            LOGGER.info("正在通过 APT 安装 %s", package_asset["name"])
            subprocess.run(
                ["apt-get", "install", "--yes", package_path],
                check=True,
            )
            LOGGER.info("Monitor 已更新到 %s", latest_version)
            return True
        finally:
            self._remove_file(package_path)

    def _validate_environment(self):
        """确认当前为具有 root 权限的 Linux 发布构建。"""
        if not sys.platform.startswith("linux"):
            raise RuntimeError("--update 仅支持通过 DEB 安装的 Linux 系统")
        if not self.repository or self.current_version == "development":
            raise RuntimeError("开发版本缺少 GitHub 发布信息，无法自动更新")
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise RuntimeError("自动安装 DEB 需要 root 权限，请使用 sudo pico-monitor --update")

    @staticmethod
    def _architecture():
        """读取 dpkg 识别的当前 Debian 软件包架构。"""
        result = subprocess.run(
            ["dpkg", "--print-architecture"],
            check=True,
            capture_output=True,
            text=True,
        )
        architecture = result.stdout.strip()
        if not architecture:
            raise RuntimeError("无法识别当前 Debian 架构")
        return architecture

    @staticmethod
    def _find_asset(assets, name):
        """按完整文件名查找 Release 资源。"""
        return next((item for item in assets if item.get("name") == name), None)

    @classmethod
    def _find_package_asset(cls, assets, architecture):
        """查找与当前 dpkg 架构匹配的 Pico Monitor DEB。"""
        suffix = "_{}.deb".format(architecture)
        matches = [
            item for item in assets
            if str(item.get("name") or "").startswith("OmniWatch_")
            and str(item.get("name") or "").endswith(suffix)
        ]
        if len(matches) != 1:
            raise RuntimeError("最新 Release 中未找到唯一的 {} 架构 DEB".format(architecture))
        return matches[0]

    @staticmethod
    def _request(url):
        """创建带 GitHub API 标识的 HTTPS 请求。"""
        return urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "pico-monitor-updater",
            },
        )

    @classmethod
    def _request_json(cls, url):
        """读取并解析 GitHub API 返回的 JSON。"""
        with urllib.request.urlopen(cls._request(url), timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    @classmethod
    def _download(cls, asset):
        """把 Release 资源下载到系统临时目录。"""
        name = str(asset.get("name") or "release-asset")
        url = asset.get("browser_download_url")
        if not url:
            raise RuntimeError("Release 资源缺少下载地址：{}".format(name))
        handle, path = tempfile.mkstemp(prefix="pico-monitor-update-", suffix="-" + name)
        os.close(handle)
        LOGGER.info("正在下载 %s", name)
        try:
            with urllib.request.urlopen(cls._request(url), timeout=120) as response, open(path, "wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
            return path
        except Exception:
            cls._remove_file(path)
            raise

    @staticmethod
    def _verify_checksum(package_path, package_name, checksum_path):
        """按 Release 摘要清单校验下载完成的 DEB 文件。"""
        expected = None
        with open(checksum_path, "r", encoding="utf-8") as checksum_file:
            for line in checksum_file:
                parts = line.strip().split(None, 1)
                listed_name = parts[1].lstrip("*") if len(parts) == 2 else ""
                if listed_name.startswith("./"):
                    listed_name = listed_name[2:]
                if len(parts) == 2 and listed_name == package_name:
                    expected = parts[0].lower()
                    break
        if expected is None:
            raise RuntimeError("摘要清单中缺少 {}".format(package_name))
        digest = hashlib.sha256()
        with open(package_path, "rb") as package_file:
            while True:
                chunk = package_file.read(64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        if digest.hexdigest().lower() != expected:
            raise RuntimeError("DEB 下载摘要校验失败")
        LOGGER.info("DEB SHA-256 校验通过")

    @staticmethod
    def _remove_file(path):
        """尽力删除更新过程中创建的临时文件。"""
        try:
            os.remove(path)
        except OSError:
            pass
