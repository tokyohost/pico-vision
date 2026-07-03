"""验证 Pico 升级包校验和串口分块发送流程。"""

import hashlib
import json
import pathlib
import tempfile
import unittest
import zipfile

from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradePackage


class FakeUpgradeSerial:
    """模拟按升级命令立即返回确认的 Pico 串口。"""

    def __init__(self):
        """初始化已发送命令和待读取响应队列。"""
        self.commands = []
        self.responses = []

    def write(self, data):
        """记录命令并生成与协议对应的确认响应。"""
        command = bytes(data).decode("ascii").strip()
        self.commands.append(command)
        if command.startswith("UPGRADE:BEGIN:"):
            self.responses.append(b"ACK:UPGRADE:BEGIN:1.0.0\n")
        elif command.startswith("UPGRADE:FILE:"):
            self.responses.append(b"ACK:UPGRADE:FILE:main.py\n")
        elif command.startswith("UPGRADE:DATA:"):
            sequence = command.split(":", 3)[2]
            self.responses.append(("ACK:UPGRADE:DATA:" + sequence + "\n").encode())
        elif command == "UPGRADE:FILE_END":
            self.responses.append(b"ACK:UPGRADE:FILE_END:main.py\n")
        elif command == "UPGRADE:COMMIT":
            self.responses.extend((b"PROGRESS:UPGRADE:INSTALL:100\n", b"ACK:UPGRADE:COMPLETE:1.0.0\n"))
        return len(data)

    def flush(self):
        """模拟立即刷新串口输出。"""

    def readline(self):
        """返回下一条 Pico 升级响应。"""
        return self.responses.pop(0) if self.responses else b""


class FakeClient:
    """提供升级器所需的最小客户端接口。"""

    def __init__(self):
        """创建模拟串口设备。"""
        self.serial = FakeUpgradeSerial()


class PicoUpgradeTests(unittest.TestCase):
    """覆盖升级包摘要校验与完整串口升级序列。"""

    def _package(self, directory, content=b"print('ok')\n", declared_hash=None):
        """在临时目录中创建单文件测试升级包。"""
        archive_path = pathlib.Path(directory) / "upgrade.zip"
        digest = declared_hash or hashlib.sha256(content).hexdigest()
        manifest = {"format": 1, "version": "1.0.0", "files": [{"path": "main.py", "size": len(content), "sha256": digest}]}
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("main.py", content)
        return archive_path

    def test_rejects_file_with_wrong_digest(self):
        """确认清单摘要不一致时不会进入串口升级。"""
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "校验失败"):
                PicoUpgradePackage(self._package(directory, declared_hash="0" * 64))

    def test_sends_package_and_commits_upgrade(self):
        """确认文件分块发送后提交安装并收到完成响应。"""
        with tempfile.TemporaryDirectory() as directory:
            package = PicoUpgradePackage(self._package(directory, content=b"x" * 900))
            client = FakeClient()
            try:
                PicoFirmwareUpgrader(client).upgrade(package)
            finally:
                package.close()
            self.assertEqual(client.serial.commands[0], "UPGRADE:BEGIN:1.0.0:1")
            self.assertEqual(client.serial.commands[-1], "UPGRADE:COMMIT")
            self.assertEqual(sum(command.startswith("UPGRADE:DATA:") for command in client.serial.commands), 3)


if __name__ == "__main__":
    unittest.main()
