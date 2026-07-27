"""验证 GPIO 按键即时触发与正数消抖行为。"""

import sys
import types
import unittest
from unittest import mock

from button_controller import GpioButton


class FakePin:
    """模拟可由测试切换输入电平的 GPIO 引脚。"""

    IN = 0
    PULL_UP = 1
    PULL_DOWN = 2

    def __init__(self, pin_id, mode, pull):
        """保存引脚配置，并默认处于上拉释放电平。"""
        self.pin_id = pin_id
        self.mode = mode
        self.pull = pull
        self.level = 1

    def value(self):
        """返回当前模拟输入电平。"""
        return self.level


class GpioButtonTest(unittest.TestCase):
    """确认零消抖即时响应且每次按下只产生一个动作。"""

    @staticmethod
    def create_button(debounce_ms):
        """使用模拟 machine.Pin 创建低电平有效按键。"""
        machine_module = types.SimpleNamespace(Pin=FakePin)
        with mock.patch.dict(sys.modules, {"machine": machine_module}):
            return GpioButton(1, "style_next", True, debounce_ms)

    def test_zero_debounce_triggers_on_press_edge_immediately(self):
        """零消抖时按下边沿同一轮应立即返回动作。"""
        button = self.create_button(0)

        button._pin.level = 0

        self.assertEqual(("style_next", "press"), button.update(100))
        self.assertIsNone(button.update(100))

    def test_zero_debounce_triggers_once_again_after_release(self):
        """释放后再次按下应立即产生下一次独立动作。"""
        button = self.create_button(0)
        button._pin.level = 0
        self.assertEqual(("style_next", "press"), button.update(100))

        button._pin.level = 1
        self.assertEqual(("style_next", "release"), button.update(110))
        button._pin.level = 0

        self.assertEqual(("style_next", "press"), button.update(120))

    def test_positive_debounce_still_requires_stable_duration(self):
        """正数消抖仍应等待输入保持到配置时长。"""
        button = self.create_button(60)
        button._pin.level = 0

        self.assertIsNone(button.update(100))
        self.assertIsNone(button.update(159))
        self.assertEqual(("style_next", "press"), button.update(160))

    def test_held_button_emits_long_press_and_fast_repeat(self):
        """持续按住应依次产生长按事件和固定周期连发事件。"""
        button = self.create_button(0)
        button.long_press_ms = 500
        button.repeat_interval_ms = 60
        button._pin.level = 0

        self.assertEqual(("style_next", "press"), button.update(100))
        self.assertIsNone(button.update(599))
        self.assertEqual(("style_next", "long_press"), button.update(600))
        self.assertIsNone(button.update(659))
        self.assertEqual(("style_next", "repeat"), button.update(660))

        button._pin.level = 1

        self.assertEqual(("style_next", "release"), button.update(720))


if __name__ == "__main__":
    unittest.main()
