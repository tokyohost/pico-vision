"""验证按键命令模式切换与各命令的事件过滤。"""

import unittest

from buttonCommand import ButtonCommandDispatcher


class FakeCommandHost:
    """记录命令分派器调用结果的测试宿主。"""

    def __init__(self):
        """初始化调用记录。"""
        self.calls = []

    def show_button_mode(self, label, snapshot):
        """记录功能键选择的模式。"""
        self.calls.append(("mode", label, snapshot))

    def execute_style_command(self, direction, snapshot):
        """记录样式切换命令。"""
        self.calls.append(("style", direction, snapshot))

    def execute_brightness_command(self, direction, snapshot):
        """记录亮度调节命令。"""
        self.calls.append(("brightness", direction, snapshot))

    def execute_rotation_command(self, direction, snapshot):
        """记录屏幕旋转命令。"""
        self.calls.append(("rotation", direction, snapshot))

    def execute_network_unit_command(self, direction, snapshot):
        """记录网络单位命令。"""
        self.calls.append(("network_unit", direction, snapshot))


class ButtonCommandDispatcherTest(unittest.TestCase):
    """确认功能键循环模式及亮度长按连发行为。"""

    def test_function_button_cycles_all_registered_modes(self):
        """功能键应按注册顺序循环四种模式。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()

        for _ in range(4):
            dispatcher.dispatch((("function", "press"),), host, {})

        self.assertEqual(
            ["亮度调节", "屏幕旋转", "网络速率单位", "样式切换"],
            [call[1] for call in host.calls],
        )

    def test_brightness_mode_accepts_press_long_press_and_repeat(self):
        """亮度模式应让短按、长按起始和连发事件全部生效。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        dispatcher.dispatch((("function", "press"),), host, {})
        host.calls = []

        dispatcher.dispatch(
            (
                ("style_next", "press"),
                ("style_next", "long_press"),
                ("style_next", "repeat"),
            ),
            host,
            {"version": 1},
        )

        self.assertEqual(
            ["brightness", "brightness", "brightness"],
            [call[0] for call in host.calls],
        )

    def test_style_mode_ignores_long_press_repeat(self):
        """样式模式长按时不得高速连续加载样式。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()

        dispatcher.dispatch(
            (
                ("style_previous", "press"),
                ("style_previous", "long_press"),
                ("style_previous", "repeat"),
            ),
            host,
            {},
        )

        self.assertEqual([("style", -1, {})], host.calls)


if __name__ == "__main__":
    unittest.main()
