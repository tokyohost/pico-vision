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
from command.sdk_bootloader import (  # noqa: E402
    SdkBootloaderCommand,
    SdkBootloaderController,
)


class SdkBootloaderCommandTest(unittest.TestCase):
    """确认只有物理 USB 会话能够触发不可逆的下载模式切换。"""

    @staticmethod
    def context(mode):
        """构造带活动传输模式和响应记录的命令上下文替身。"""
        transport = mock.Mock()
        transport.active_mode.return_value = mode
        led = mock.Mock()
        controller = mock.Mock()
        context = mock.Mock()
        context.request_id = "sdk-test"
        context.service.side_effect = lambda name, required=True: (
            transport
            if name == "transport"
            else controller
            if name == "sdk_bootloader"
            else led
        )
        context.test_transport = transport
        context.test_led = led
        context.test_controller = controller
        return context

    def test_websocket_request_is_rejected_before_bootloader_call(self):
        """WebSocket 客户端不能远程触发设备离线并进入刷写模式。"""
        context = self.context("wifi")

        with self.assertRaisesRegex(CommandError, "REQUIRES_USB"):
            SdkBootloaderCommand().execute({}, context)

        context.respond.assert_not_called()

    def test_usb_request_is_acknowledged_before_main_loop_switch(self):
        """物理 USB 请求应先刷新 ACK，再登记主循环切换请求。"""
        context = self.context("usb")
        machine = types.SimpleNamespace(bootloader=mock.Mock())

        with mock.patch.dict(sys.modules, {"machine": machine}):
            SdkBootloaderCommand().execute({}, context)

        context.respond.assert_called_once_with(
            "ok",
            "sdk.bootloader",
            {"restarting": True, "mode": "rom-usb"},
            "sdk-test",
        )
        context.test_transport.flush.assert_called_once_with()
        context.test_controller.request.assert_called_once_with()
        machine.bootloader.assert_not_called()

    def test_controller_switches_only_after_returning_to_main_loop(self):
        """主循环安全点应停止后台服务后再调用 bootloader。"""
        controller = SdkBootloaderController(delay_ms=300)
        renderer = mock.Mock()
        transport = mock.Mock()
        led = mock.Mock()
        machine = types.SimpleNamespace(bootloader=mock.Mock())

        with mock.patch("command.sdk_bootloader._ticks_ms", side_effect=[1000, 1200, 1300]):
            controller.request()
            self.assertFalse(controller.process(renderer, transport, led))
            with mock.patch.dict(sys.modules, {"machine": machine}):
                with self.assertRaises(SystemExit):
                    controller.process(renderer, transport, led)

        renderer.stop.assert_called_once_with()
        transport.close.assert_called_once_with()
        led.off.assert_called_once_with()
        machine.bootloader.assert_called_once_with()
        self.assertFalse(controller.pending())

    def test_sdk_without_bootloader_capability_is_rejected(self):
        """旧 SDK 缺少 machine.bootloader 时必须返回明确的不支持错误。"""
        context = self.context("usb")
        machine = types.SimpleNamespace()

        with mock.patch.dict(sys.modules, {"machine": machine}):
            with self.assertRaisesRegex(CommandError, "UNSUPPORTED"):
                SdkBootloaderCommand().execute({}, context)


if __name__ == "__main__":
    unittest.main()
