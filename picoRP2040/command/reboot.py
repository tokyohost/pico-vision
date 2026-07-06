"""实现设备软重启命令策略。"""

import time

from command.base import CommandStrategy


class RebootCommand(CommandStrategy):
    """确认命令后执行 RP2040 软重启。"""

    name = "reboot"

    def execute(self, params, context):
        """先发送成功响应，再延迟执行设备复位。"""
        context.respond("ok", self.name, {"restarting": True}, context.request_id)
        sleep_ms = getattr(time, "sleep_ms", None)
        if sleep_ms is not None:
            sleep_ms(100)
        else:
            time.sleep(0.1)
        try:
            import machine
            machine.reset()
        except ImportError:
            raise SystemExit("设备需要重启")


COMMAND_STRATEGY = RebootCommand()
