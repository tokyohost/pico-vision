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



"""验证 Pico 升级包校验和串口分块发送流程。"""


import base64
import hashlib
import json
import pathlib
import tempfile
import unittest
import zlib
import zipfile

from pico_upgrade import PicoFirmwareUpgrader, PicoUpgradePackage
from pico_client import PicoJsonClient, build_frame, parse_frame


class FakeUpgradeSerial:
    """模拟按升级命令立即返回确认的 Pico 串口。"""

    def __init__(self):
        """初始化已发送命令和待读取响应队列。"""
        self.commands = []
        self.packets = []
        self.responses = []

    def write(self, data):
        """记录命令并生成与协议对应的确认响应。"""
        self.packets.append(bytes(data))
        frame = parse_frame(data)
        self.assert_frame = frame
        compressed = base64.b64decode(frame[1])
        message = json.loads(zlib.decompress(compressed))
        params = message["params"]
        command = params["action"]
        self.commands.append(command)
        if command == "begin":
            self.responses.append(build_frame("STATUS", b"ACK:UPGRADE:BEGIN:1.0.0"))
        elif command == "file":
            self.responses.append(build_frame("STATUS", b"ACK:UPGRADE:FILE:main.py"))
        elif command == "data":
            sequence = str(params["sequence"])
            self.responses.append(build_frame("STATUS", ("ACK:UPGRADE:DATA:" + sequence).encode()))
        elif command == "file_end":
            self.responses.append(build_frame("STATUS", b"ACK:UPGRADE:FILE_END:main.py"))
        elif command == "commit":
            self.responses.extend((
                build_frame("STATUS", b"PROGRESS:UPGRADE:INSTALL:100"),
                build_frame("STATUS", b"ACK:UPGRADE:COMPLETE:1.0.0"),
            ))
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

    build_command_packet = staticmethod(PicoJsonClient.build_command_packet)


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
            self.assertEqual(client.serial.commands[0], "begin")
            self.assertEqual(client.serial.commands[-1], "commit")
            self.assertEqual(client.serial.commands.count("data"), 3)
            self.assertTrue(all(parse_frame(packet)[0] == "JSONZ" for packet in client.serial.packets))
            self.assertTrue(all(packet.endswith(b"\n") for packet in client.serial.packets))


if __name__ == "__main__":
    unittest.main()
