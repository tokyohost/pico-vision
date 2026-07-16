"""验证 ESP32-S3 SDK 下载模式命令的 USB 安全边界。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ESP32_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

from command.base import CommandError  # noqa: E402
from command.sdk_bootloader import SdkBootloaderCommand  # noqa: E402


class SdkBootloaderCommandTest(unittest.TestCase):
    """确认只有物理 USB 会话能够触发不可逆的下载模式切换。"""

    @staticmethod
    def context(mode):
        """构造带活动传输模式和响应记录的命令上下文替身。"""
        transport = mock.Mock()
        transport.active_mode.return_value = mode
        context = mock.Mock()
        context.request_id = "sdk-test"
        context.service.return_value = transport
        return context

    def test_websocket_request_is_rejected_before_bootloader_call(self):
        """WebSocket 客户端不能远程触发设备离线并进入刷写模式。"""
        context = self.context("wifi")

        with self.assertRaisesRegex(CommandError, "REQUIRES_USB"):
            SdkBootloaderCommand().execute({}, context)

        context.respond.assert_not_called()

    def test_usb_request_is_acknowledged_before_entering_bootloader(self):
        """物理 USB 请求应先返回 ACK，再调用 SDK 的 bootloader 能力。"""
        context = self.context("usb")
        machine = types.SimpleNamespace(bootloader=mock.Mock())

        with mock.patch.dict(sys.modules, {"machine": machine}):
            with mock.patch("command.sdk_bootloader.time.sleep"):
                with self.assertRaises(SystemExit):
                    SdkBootloaderCommand().execute({}, context)

        context.respond.assert_called_once_with(
            "ok",
            "sdk.bootloader",
            {"restarting": True, "mode": "rom-usb"},
            "sdk-test",
        )
        machine.bootloader.assert_called_once_with()

    def test_sdk_without_bootloader_capability_is_rejected(self):
        """旧 SDK 缺少 machine.bootloader 时必须返回明确的不支持错误。"""
        context = self.context("usb")
        machine = types.SimpleNamespace()

        with mock.patch.dict(sys.modules, {"machine": machine}):
            with self.assertRaisesRegex(CommandError, "UNSUPPORTED"):
                SdkBootloaderCommand().execute({}, context)


if __name__ == "__main__":
    unittest.main()
