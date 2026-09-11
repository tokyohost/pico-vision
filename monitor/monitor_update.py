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

    def update(self, progress_callback=None):
        """检查、下载并安装最新 DEB，同时向调用方持续报告可见进度。"""
        self._validate_environment()
        self._report_progress(progress_callback, "正在检查最新 Linux Release", 2)
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
            self._report_progress(
                progress_callback,
                "当前已是最新版本：{}".format(self.current_version),
                100,
            )
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
        self._report_progress(
            progress_callback,
            "发现新版本 {}，准备下载 {}".format(
                latest_version, package_asset["name"]
            ),
            5,
        )
        last_percent = [-1]
        last_unknown_megabyte = [-1]

        def report_package_download(downloaded_bytes, total_bytes):
            """把 DEB 下载字节数转换为页面百分比和中文日志。"""
            if total_bytes:
                percent = min(100, int(downloaded_bytes * 100 / total_bytes))
                if percent == last_percent[0]:
                    return
                last_percent[0] = percent
                message = "正在下载 Linux DEB：{}%（{} / {}）".format(
                    percent,
                    self._format_size(downloaded_bytes),
                    self._format_size(total_bytes),
                )
                self._report_progress(
                    progress_callback, message, 5 + int(percent * 0.70)
                )
                return
            downloaded_megabyte = downloaded_bytes // (1024 * 1024)
            if downloaded_megabyte == last_unknown_megabyte[0]:
                return
            last_unknown_megabyte[0] = downloaded_megabyte
            self._report_progress(
                progress_callback,
                "正在下载 Linux DEB：已下载 {}".format(
                    self._format_size(downloaded_bytes)
                ),
                None,
            )

        package_path = self._download(
            package_asset, progress_callback=report_package_download
        )
        try:
            self._report_progress(
                progress_callback, "Linux DEB 下载完成，正在校验", 78
            )
            if checksum_asset is not None:
                checksum_path = self._download(checksum_asset)
                try:
                    self._verify_checksum(
                        package_path,
                        package_asset["name"],
                        checksum_path,
                    )
                    self._report_progress(
                        progress_callback, "Linux DEB SHA-256 校验通过", 85
                    )
                finally:
                    self._remove_file(checksum_path)
            else:
                LOGGER.warning("Release 未提供 %s，跳过独立摘要校验", CHECKSUM_ASSET_NAME)
            LOGGER.info("正在通过 APT 安装 %s", package_asset["name"])
            self._report_progress(
                progress_callback,
                "正在通过 APT 安装 {}".format(package_asset["name"]),
                90,
            )
            subprocess.run(
                ["apt-get", "install", "--yes", package_path],
                check=True,
            )
            LOGGER.info("Monitor 已更新到 %s", latest_version)
            self._report_progress(
                progress_callback,
                "OmniWatch Linux 应用已更新到 {}".format(latest_version),
                100,
            )
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
    def _download(cls, asset, progress_callback=None):
        """把 Release 资源下载到系统临时目录，并按数据块报告字节进度。"""
        name = str(asset.get("name") or "release-asset")
        url = asset.get("browser_download_url")
        if not url:
            raise RuntimeError("Release 资源缺少下载地址：{}".format(name))
        handle, path = tempfile.mkstemp(prefix="pico-monitor-update-", suffix="-" + name)
        os.close(handle)
        LOGGER.info("正在下载 %s", name)
        try:
            with urllib.request.urlopen(cls._request(url), timeout=120) as response, open(path, "wb") as output:
                total_bytes = cls._response_content_length(response)
                downloaded_bytes = 0
                if progress_callback is not None:
                    progress_callback(downloaded_bytes, total_bytes)
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded_bytes += len(chunk)
                    if progress_callback is not None:
                        progress_callback(downloaded_bytes, total_bytes)
            return path
        except Exception:
            cls._remove_file(path)
            raise

    @staticmethod
    def _response_content_length(response):
        """读取 HTTP 响应声明的文件大小，无有效响应头时返回空值。"""
        try:
            value = response.headers.get("Content-Length")
            return max(0, int(value)) if value is not None else None
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _format_size(byte_count):
        """把字节数格式化为便于页面日志阅读的容量文本。"""
        value = float(max(0, int(byte_count or 0)))
        units = ("B", "KB", "MB", "GB")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return "{:.1f} {}".format(value, unit)
            value /= 1024

    @staticmethod
    def _report_progress(progress_callback, message, progress):
        """同时写入服务日志，并把阶段消息转发给 HTTP 更新状态。"""
        LOGGER.info("%s", message)
        if progress_callback is not None:
            progress_callback(message, progress)

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
