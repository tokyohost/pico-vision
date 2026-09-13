"""验证按键命令模式切换与各命令的事件过滤。"""

import unittest

from buttonCommand import ButtonCommandDispatcher


class FakeCommandHost:
    """记录命令分派器调用结果的测试宿主。"""

    def __init__(self):
        """初始化调用记录。"""
        self.calls = []
        self.handled_events = set()

    def notify_style_button_event(self, button, event_type, snapshot):
        """记录透传给样式的事件，并按测试配置决定是否消费。"""
        self.calls.append(("listener", button, event_type, snapshot))
        return (button, event_type) in self.handled_events

    def show_button_mode(self, label, snapshot):
        """记录功能键选择的模式。"""
        self.calls.append(("mode", label, snapshot))

    def execute_style_command(self, direction, snapshot):
        """记录样式切换命令。"""
        self.calls.append(("style", direction, snapshot))

    def execute_brightness_command(self, direction, snapshot):
        """记录亮度调节命令。"""
        self.calls.append(("brightness", direction, snapshot))

    def commit_brightness_command(self):
        """记录亮度最终值同步命令。"""
        self.calls.append(("brightness_commit",))

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
            [call[1] for call in host.calls if call[0] == "mode"],
        )

    def test_brightness_mode_commits_once_after_release(self):
        """亮度模式应连续调节本机，并在释放时仅同步一次。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        dispatcher.dispatch((("function", "press"),), host, {})
        host.calls = []

        dispatcher.dispatch(
            (
                ("style_next", "press"),
                ("style_next", "long_press"),
                ("style_next", "repeat"),
                ("style_next", "release"),
            ),
            host,
            {"version": 1},
        )

        self.assertEqual(
            ["brightness", "brightness", "brightness", "brightness_commit"],
            [call[0] for call in host.calls if call[0] != "listener"],
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

        self.assertEqual(
            [("style", -1, {})],
            [call for call in host.calls if call[0] != "listener"],
        )

    def test_style_listener_receives_all_events_and_can_consume_default(self):
        """主题监听器应收到物理键事件，并可阻止对应默认命令。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        host.handled_events.add(("style_next", "press"))

        dispatcher.dispatch(
            (("style_next", "press"), ("style_next", "release")),
            host,
            {"version": 2},
        )

        self.assertEqual(
            [
                ("listener", "style_next", "press", {"version": 2}),
                ("listener", "style_next", "release", {"version": 2}),
            ],
            [call for call in host.calls if call[0] == "listener"],
        )
        self.assertNotIn(("style", 1, {"version": 2}), host.calls)


if __name__ == "__main__":
    unittest.main()
