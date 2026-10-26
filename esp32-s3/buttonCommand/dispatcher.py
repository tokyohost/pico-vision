"""使用命令模式分派三枚物理按键产生的事件。"""

from i18n import t

from buttonCommand.commands import (
    BrightnessCommand,
    NetworkUnitCommand,
    RotationCommand,
    StyleSwitchCommand,
)


class ButtonCommandDispatcher:
    """优先处理系统菜单，再把快捷操作交给当前模式。"""

    def __init__(self):
        """按样式、亮度、旋转、网络单位顺序注册命令。"""
        self._commands = (
            StyleSwitchCommand(),
            BrightnessCommand(),
            RotationCommand(),
            NetworkUnitCommand(),
        )
        self._index = 0
        self._function_pressed = False
        self._function_long = False

    def current(self):
        """返回当前生效的按键命令。"""
        return self._commands[self._index]

    def dispatch(self, events, host, snapshot):
        """区分功能键长短按，并隔离菜单事件与样式快捷事件。"""
        for action, event_type in events:
            if action == "function":
                if event_type == "press":
                    self._function_pressed = True
                    self._function_long = False
                    continue
                if event_type == "long_press" and self._function_pressed:
                    self._function_long = True
                    if not host.system_menu_active():
                        host.open_system_menu()
                    continue
                if event_type != "release" or not self._function_pressed:
                    continue
                self._function_pressed = False
                if self._function_long:
                    continue
                if host.system_menu_active():
                    host.handle_system_menu_event(action, "press", snapshot)
                    continue
                # 松手确认短按后才通知样式，长按不会泄漏为快捷操作。
                consumed = host.notify_style_button_event(action, "press", snapshot)
                host.notify_style_button_event(action, "release", snapshot)
                if not consumed:
                    self._index = (self._index + 1) % len(self._commands)
                    host.show_button_mode(t(self.current().label_key), snapshot)
                continue
            if host.system_menu_active():
                host.handle_system_menu_event(action, event_type, snapshot)
                continue
            listener = getattr(host, "notify_style_button_event", None)
            if callable(listener) and listener(action, event_type, snapshot):
                continue
            if action not in ("style_previous", "style_next"):
                continue
            direction = -1 if action == "style_previous" else 1
            self.current().execute(host, direction, event_type, snapshot)
