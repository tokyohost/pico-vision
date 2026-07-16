"""实现仅允许通过物理 USB 进入 ESP32-S3 ROM 下载模式的命令。"""

import time

from command.base import CommandError, CommandStrategy


class SdkBootloaderCommand(CommandStrategy):
    """确认主机请求后受控切换到 ESP32-S3 ROM USB 下载模式。"""

    name = "sdk.bootloader"

    def execute(self, params, context):
        """校验活动传输和 SDK 能力，回复成功后再进入下载模式。"""
        del params
        transport = context.service("transport")
        if transport.active_mode() != "usb":
            raise CommandError("SDK_BOOTLOADER_REQUIRES_USB")
        try:
            import machine
        except ImportError as error:
            raise CommandError("SDK_BOOTLOADER_UNSUPPORTED") from error
        bootloader = getattr(machine, "bootloader", None)
        if not callable(bootloader):
            raise CommandError("SDK_BOOTLOADER_UNSUPPORTED")

        context.respond(
            "ok",
            self.name,
            {"restarting": True, "mode": "rom-usb"},
            context.request_id,
        )
        sleep_ms = getattr(time, "sleep_ms", None)
        if sleep_ms is not None:
            sleep_ms(300)
        else:
            time.sleep(0.3)
        bootloader()
        raise SystemExit("设备正在进入 ROM USB 下载模式")


COMMAND_STRATEGY = SdkBootloaderCommand()
