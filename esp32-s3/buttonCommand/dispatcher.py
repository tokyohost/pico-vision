"""使用命令模式分派三枚物理按键产生的事件。"""

from buttonCommand.commands import (
    BrightnessCommand,
    NetworkUnitCommand,
    RotationCommand,
    StyleSwitchCommand,
)


class ButtonCommandDispatcher:
    """维护功能键选择的模式，并把方向键交给当前命令。"""

    def __init__(self):
        """按样式、亮度、旋转、网络单位顺序注册命令。"""
        self._commands = (
            StyleSwitchCommand(),
            BrightnessCommand(),
            RotationCommand(),
            NetworkUnitCommand(),
        )
        self._index = 0

    def current(self):
        """返回当前生效的按键命令。"""
        return self._commands[self._index]

    def dispatch(self, events, host, snapshot):
        """先通知当前样式，再由未消费的事件执行设备默认命令。"""
        for action, event_type in events:
            listener = getattr(host, "notify_style_button_event", None)
            if callable(listener) and listener(action, event_type, snapshot):
                continue
            if action == "function":
                if event_type == "press":
                    self._index = (self._index + 1) % len(self._commands)
                    host.show_button_mode(self.current().label, snapshot)
                continue
            direction = -1 if action == "style_previous" else 1
            self.current().execute(host, direction, event_type, snapshot)
