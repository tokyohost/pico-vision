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



"""下载、校验 Pico 升级包，并通过串口可靠发送其中的固件文件。"""


import base64
import hashlib
import json
import logging
import os
import tempfile
import time
import urllib.request
import zipfile

from pico_client import parse_frame


LOGGER = logging.getLogger("pico-monitor.upgrade")
UPGRADE_CHUNK_SIZE = 384


class PicoUpgradePackage:
    """表示已通过清单与文件摘要校验的 Pico 升级包。"""

    def __init__(self, archive_path):
        """打开 ZIP 升级包并验证清单中声明的全部文件。"""
        self.archive_path = archive_path
        self.archive = zipfile.ZipFile(archive_path, "r")
        self.manifest = json.loads(self.archive.read("manifest.json").decode("utf-8"))
        self.version = str(self.manifest["version"])
        self.files = self.manifest["files"]
        if not self.files:
            raise ValueError("升级包不包含固件文件")
        for item in self.files:
            data = self.archive.read(item["path"])
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != item["size"] or digest != item["sha256"]:
                raise ValueError("升级包文件校验失败：{}".format(item["path"]))

    def close(self):
        """关闭升级包文件句柄。"""
        self.archive.close()


class PicoUpgradeDownloader:
    """从指定地址下载当前 Monitor 版本对应的 Pico 升级包。"""

    @staticmethod
    def download(url, expected_sha256=None):
        """下载升级包到临时文件，并按可选摘要进行传输校验。"""
        LOGGER.info("[升级下载] %s", url)
        handle, path = tempfile.mkstemp(prefix="pico-upgrade-", suffix=".zip")
        os.close(handle)
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(path, "wb") as output:
                total = int(response.headers.get("Content-Length", "0") or 0)
                received = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / total) if total else 0
                    LOGGER.info("[升级下载] 已接收 %d 字节，进度 %d%%", received, percent)
            actual = digest.hexdigest()
            if expected_sha256 and actual.lower() != expected_sha256.lower():
                raise ValueError("升级包下载摘要不匹配")
            LOGGER.info("[升级下载] 完成，SHA-256=%s", actual)
            return path
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise


class PicoFirmwareUpgrader:
    """通过 PicoJsonClient 的串口连接执行固件升级。"""

    def __init__(self, client):
        """保存已连接的 Pico 串口客户端。"""
        self.client = client

    def upgrade(self, package):
        """依次发送升级会话、文件数据和提交命令。"""
        serial_device = self.client.serial
        self._command({"action": "begin", "version": package.version, "file_count": len(package.files)}, "ACK:UPGRADE:BEGIN:")
        sent_total = 0
        package_total = sum(item["size"] for item in package.files)
        for item in package.files:
            path = item["path"]
            data = package.archive.read(path)
            self._command({"action": "file", "path": path, "size": len(data), "sha256": item["sha256"]}, "ACK:UPGRADE:FILE:")
            for sequence, position in enumerate(range(0, len(data), UPGRADE_CHUNK_SIZE)):
                encoded = base64.b64encode(data[position:position + UPGRADE_CHUNK_SIZE]).decode("ascii")
                self._command({"action": "data", "sequence": sequence, "data": encoded}, "ACK:UPGRADE:DATA:{}".format(sequence))
                sent_total += min(UPGRADE_CHUNK_SIZE, len(data) - position)
                LOGGER.info("[升级发送] %s，整体进度 %d%%", path, int(sent_total * 100 / package_total))
            self._command({"action": "file_end"}, "ACK:UPGRADE:FILE_END:")
        LOGGER.info("[升级安装] Pico 正在校验并替换内部文件")
        serial_device.write(self._build_command_packet({"action": "commit"}))
        serial_device.flush()
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = self._response_text(serial_device.readline())
            if not response:
                continue
            LOGGER.info("[Pico -> Monitor][升级] %s", response)
            if response.startswith("ACK:UPGRADE:COMPLETE:"):
                LOGGER.info("[升级完成] Pico 已完成升级并将自动重启")
                return
            if response.startswith("ERR:"):
                raise RuntimeError(response)
        raise RuntimeError("等待 Pico 安装升级包超时")

    def _command(self, params, expected_prefix):
        """发送单条升级命令并等待对应确认响应。"""
        device = self.client.serial
        LOGGER.debug("[Monitor -> Pico][升级] %s", params)
        device.write(self._build_command_packet(params))
        device.flush()
        for _ in range(100):
            response = self._response_text(device.readline())
            if not response:
                continue
            LOGGER.info("[Pico -> Monitor][升级] %s", response)
            if response.startswith(expected_prefix):
                return
            if response.startswith("ERR:"):
                raise RuntimeError(response)
        raise RuntimeError("等待 Pico 升级确认超时：{}".format(params.get("action")))

    def _build_command_packet(self, params):
        """把升级参数编码为统一 JSON 命令帧。"""
        return self.client.build_command_packet("upgrade", params)

    @staticmethod
    def _response_text(data):
        """读取并校验 PV1 状态帧。"""
        if not data:
            return ""
        try:
            frame = parse_frame(data)
        except ValueError as error:
            raise RuntimeError("Pico 返回损坏升级帧：{}".format(error)) from error
        if frame is not None:
            if frame[0] not in ("STATUS", "ERR"):
                return ""
            return frame[1].decode("utf-8", errors="replace")
        raise RuntimeError("Pico 返回非 PV1 升级响应")
