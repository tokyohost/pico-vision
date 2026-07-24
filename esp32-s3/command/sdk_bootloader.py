"""实现仅允许通过物理 USB 进入 ESP32-S3 ROM 下载模式的命令。"""

import time

from command.base import CommandError, CommandStrategy


def _enter_rom_usb_bootloader(led):
    """在命令响应栈退出后延迟切换到 ESP32-S3 ROM USB 下载模式。"""
    turn_off = getattr(led, "off", None)
    if callable(turn_off):
        turn_off()
    sleep_ms = getattr(time, "sleep_ms", None)
    if sleep_ms is not None:
        sleep_ms(300)
    else:
        time.sleep(0.3)
    import machine

    machine.bootloader()
    raise SystemExit("设备正在进入 ROM USB 下载模式")


class SdkBootloaderCommand(CommandStrategy):
    """确认主机请求后受控切换到 ESP32-S3 ROM USB 下载模式。"""

    name = "sdk.bootloader"

    def execute(self, params, context):
        """校验活动传输和 SDK 能力，回复成功后调度进入下载模式。"""
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
        try:
            import micropython
        except ImportError as error:
            raise CommandError("SDK_BOOTLOADER_SCHEDULER_UNAVAILABLE") from error
        schedule = getattr(micropython, "schedule", None)
        if not callable(schedule):
            raise CommandError("SDK_BOOTLOADER_SCHEDULER_UNAVAILABLE")

        context.respond(
            "ok",
            self.name,
            {"restarting": True, "mode": "rom-usb"},
            context.request_id,
        )
        flush = getattr(transport, "flush", None)
        if callable(flush):
            flush()
        led = context.service("led", required=False)
        try:
            schedule(_enter_rom_usb_bootloader, led)
        except RuntimeError:
            # 调度队列意外占满时直接执行，确保已经返回成功 ACK 的请求不会失效。
            _enter_rom_usb_bootloader(led)


COMMAND_STRATEGY = SdkBootloaderCommand()
