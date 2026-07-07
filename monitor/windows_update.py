"""为 Windows 托盘发现、下载并安装最新发布版本。"""

import hashlib
import json
import os
import platform
import tempfile
import urllib.request
from pathlib import Path


class WindowsReleaseUpdater:
    """管理 Windows Monitor 与 Pico 固件的联合在线更新。"""

    def __init__(self, repository, current_version):
        """保存默认发布仓库和当前 Monitor 版本。"""
        self.repository = str(repository or "").strip()
        self.current_version = str(current_version or "").strip()

    def default_update_url(self):
        """返回正式构建内置的默认更新元数据地址。"""
        if not self.repository:
            return ""
        return "https://api.github.com/repos/{}/releases/latest".format(self.repository)

    def latest_release(self, update_url=None):
        """读取最新发布元数据，并返回规范化版本与资源清单。"""
        url = str(update_url or self.default_update_url()).strip()
        if not url:
            raise RuntimeError("未配置更新地址")
        release = self._request_json(url)
        version = str(release.get("tag_name") or "").lstrip("v")
        if not version:
            raise RuntimeError("更新元数据缺少版本标签")
        return version, release.get("assets") or []

    def update_available(self, latest_version):
        """判断最新 Release 是否与当前版本不同。"""
        return str(latest_version) != self.current_version

    def select_monitor_asset(self, assets):
        """按当前 Python 进程位数选择 Windows Monitor 安装包。"""
        architecture = "x64" if platform.architecture()[0] == "64bit" else "x86"
        return self._required_asset(
            assets, "OmniWatch-windows-{}-setup.exe".format(architecture)
        )

    @classmethod
    def select_pico_asset(cls, assets, version):
        """选择默认硬件组合兼容的 Pico 升级包。"""
        return cls._required_asset(assets, "OmniWatch-pico-upgrade-v{}.zip".format(version))

    def download(self, asset, suffix):
        """下载发布资源，并校验服务端提供的 SHA-256 摘要。"""
        url = asset.get("browser_download_url")
        if not url:
            raise RuntimeError("Release 资源缺少下载地址：{}".format(asset.get("name")))
        handle, path = tempfile.mkstemp(prefix="pico-windows-update-", suffix=suffix)
        os.close(handle)
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(self._request(url), timeout=120) as response, open(path, "wb") as output:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
            expected = str(asset.get("digest") or "")
            if expected.startswith("sha256:") and digest.hexdigest().lower() != expected[7:].lower():
                raise RuntimeError("下载文件 SHA-256 校验失败：{}".format(asset.get("name")))
            return Path(path)
        except Exception:
            self.remove_file(path)
            raise

    @staticmethod
    def _required_asset(assets, name):
        """按完整名称获取必需的 Release 资源。"""
        asset = next((item for item in assets if item.get("name") == name), None)
        if asset is None:
            raise RuntimeError("最新 Release 缺少资源：{}".format(name))
        return asset

    @staticmethod
    def _request(url):
        """创建带更新客户端标识的 HTTPS 请求。"""
        return urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "pico-monitor-windows-updater",
        })

    @classmethod
    def _request_json(cls, url):
        """读取并解析更新元数据 JSON。"""
        with urllib.request.urlopen(cls._request(url), timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def remove_file(path):
        """尽力删除更新过程创建的临时文件。"""
        try:
            Path(path).unlink()
        except OSError:
            pass
