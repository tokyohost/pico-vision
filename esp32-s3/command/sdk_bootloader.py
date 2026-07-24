"""实现仅允许通过物理 USB 进入 ESP32-S3 ROM 下载模式的命令。"""

import time

from command.base import CommandError, CommandStrategy


def _ticks_ms():
    """返回兼容 MicroPython 与 CPython 的单调毫秒时间。"""
    provider = getattr(time, "ticks_ms", None)
    return provider() if callable(provider) else int(time.monotonic() * 1000)


def _ticks_diff(current, started):
    """计算可兼容 MicroPython 计时回绕的毫秒差值。"""
    provider = getattr(time, "ticks_diff", None)
    return provider(current, started) if callable(provider) else current - started


class SdkBootloaderController:
    """在应用主循环安全点执行 ROM USB 下载模式切换。"""

    def __init__(self, delay_ms=300):
        """设置 ACK 排空等待时间并初始化空闲状态。"""
        self._delay_ms = max(1, int(delay_ms))
        self._requested_ms = None

    def request(self):
        """登记一次下载模式请求，重复请求不会延后首次切换。"""
        if self._requested_ms is None:
            self._requested_ms = _ticks_ms()

    def pending(self):
        """返回当前是否存在尚未执行的下载模式请求。"""
        return self._requested_ms is not None

    def process(self, renderer=None, transport=None, led=None):
        """在 ACK 排空后停止后台服务并从主循环切换 USB 控制器。"""
        if self._requested_ms is None:
            return False
        if _ticks_diff(_ticks_ms(), self._requested_ms) < self._delay_ms:
            return False
        self._requested_ms = None

        stop_renderer = getattr(renderer, "stop", None)
        if callable(stop_renderer):
            stop_renderer()
        close_transport = getattr(transport, "close", None)
        if callable(close_transport):
            close_transport()
        turn_off = getattr(led, "off", None)
        if callable(turn_off):
            turn_off()

        import machine

        machine.bootloader()
        raise SystemExit("设备正在进入 ROM USB 下载模式")


class SdkBootloaderCommand(CommandStrategy):
    """确认主机请求后受控切换到 ESP32-S3 ROM USB 下载模式。"""

    name = "sdk.bootloader"

    def execute(self, params, context):
        """校验物理 USB 请求，回复成功后交由应用主循环执行切换。"""
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
        controller = context.service("sdk_bootloader")
        context.respond(
            "ok",
            self.name,
            {"restarting": True, "mode": "rom-usb"},
            context.request_id,
        )
        flush = getattr(transport, "flush", None)
        if callable(flush):
            flush()
        # 命令此时仍位于 USB 读取和 PV1 解析调用栈中，不能在这里
        # 释放 OTG PHY；返回主循环后再停止服务并进入 ROM。
        controller.request()


COMMAND_STRATEGY = SdkBootloaderCommand()
