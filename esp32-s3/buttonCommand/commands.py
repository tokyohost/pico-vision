"""定义样式、亮度、旋转和网络单位按键命令。"""


class ButtonCommand:
    """声明按键模式命令的统一执行接口。"""

    name = "base"
    label = "未知模式"

    def execute(self, host, direction, event_type, snapshot):
        """执行当前模式命令，子类必须实现具体行为。"""
        raise NotImplementedError


class StyleSwitchCommand(ButtonCommand):
    """根据方向切换上一个或下一个屏幕样式。"""

    name = "style"
    label = "样式切换"

    def execute(self, host, direction, event_type, snapshot):
        """仅在首次按下时切换一次样式。"""
        if event_type == "press":
            host.execute_style_command(direction, snapshot)


class BrightnessCommand(ButtonCommand):
    """短按单步、长按连续调节屏幕亮度。"""

    name = "brightness"
    label = "亮度调节"

    def execute(self, host, direction, event_type, snapshot):
        """调节本机亮度，并在按键释放时统一同步最终值。"""
        if event_type in ("press", "long_press", "repeat"):
            host.execute_brightness_command(direction, snapshot)
        elif event_type == "release":
            host.commit_brightness_command()


class RotationCommand(ButtonCommand):
    """使用上一键和下一键选择屏幕旋转方向。"""

    name = "rotation"
    label = "屏幕旋转"

    def execute(self, host, direction, event_type, snapshot):
        """首次按下时选择零度或一百八十度。"""
        if event_type == "press":
            host.execute_rotation_command(direction, snapshot)


class NetworkUnitCommand(ButtonCommand):
    """使用上一键和下一键选择网络速率单位。"""

    name = "network_unit"
    label = "网络速率单位"

    def execute(self, host, direction, event_type, snapshot):
        """首次按下时选择 MB 或 Mbps。"""
        if event_type == "press":
            host.execute_network_unit_command(direction, snapshot)
