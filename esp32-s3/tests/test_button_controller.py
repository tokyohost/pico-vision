"""验证 GPIO 按键即时触发与正数消抖行为。"""

import json
import re
import sys
import types
import unittest
from pathlib import Path
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


class ButtonConfigurationTest(unittest.TestCase):
    """确认屏幕方案默认按键与持久化覆盖配置在启动时正确生效。"""

    @staticmethod
    def load_configuration(device_type, runtime_values=None):
        """在隔离命名空间模拟型号选择与运行配置文件，不改写实际源码。"""
        path = Path(__file__).resolve().parents[1] / "config.py"
        source = re.sub(
            r'(?m)^LCD_DEVICE_TYPE = "[^"]*"$',
            "LCD_DEVICE_TYPE = " + repr(device_type),
            path.read_text(encoding="utf-8"),
        )
        configuration = {}
        runtime_file = mock.mock_open(read_data=json.dumps(runtime_values or {}))
        if runtime_values is None:
            runtime_file.side_effect = FileNotFoundError
        with mock.patch("builtins.open", runtime_file):
            exec(compile(source, str(path), "exec"), configuration)
        return configuration

    def test_backpcb_canonical_and_alias_use_three_board_keys(self):
        """规范型号与别名均应把 K1/K2/K3 映射为 GPIO1/2/42。"""
        for device_type in (
            "st7789-2.4inch-10pin-backpcb",
            "st7789_2_4inch_10pin_backpcb",
            " ST7789_2_4INCH_10PIN_BACKPCB ",
        ):
            with self.subTest(device_type=device_type):
                configuration = self.load_configuration(device_type)
                self.assertEqual(
                    tuple(configuration[name] for name in (
                        "PIN_BUTTON_STYLE_PREVIOUS", "PIN_BUTTON_STYLE_NEXT",
                        "PIN_BUTTON_FUNCTION",
                    )),
                    (1, 2, 42),
                )
                self.assertTrue(configuration["BUTTON_ACTIVE_LOW"])
                self.assertEqual(configuration["BUTTON_DEBOUNCE_MS"], 0)
                self.assertEqual(configuration["BUTTON_LONG_PRESS_MS"], 500)
                self.assertEqual(configuration["BUTTON_REPEAT_INTERVAL_MS"], 60)

    def test_existing_panels_keep_original_button_pins(self):
        """原有八针和十针屏继续使用 GPIO1/2/3，避免背板配置影响旧设备。"""
        for device_type in (
            "st7789-2inch-8pin-a", "st7789-2.4inch-8pin-b",
            "st7789-2.4inch-10pin-a", "st7789_2_4inch_10pin_a",
        ):
            with self.subTest(device_type=device_type):
                configuration = self.load_configuration(device_type)
                self.assertEqual(
                    tuple(configuration[name] for name in (
                        "PIN_BUTTON_STYLE_PREVIOUS", "PIN_BUTTON_STYLE_NEXT",
                        "PIN_BUTTON_FUNCTION",
                    )),
                    (1, 2, 3),
                )

    def test_runtime_button_configuration_overrides_board_defaults(self):
        """持久化引脚、有效电平和按键时序应优先于背板默认配置。"""
        overrides = {
            "PIN_BUTTON_STYLE_PREVIOUS": 18,
            "PIN_BUTTON_STYLE_NEXT": 8,
            "PIN_BUTTON_FUNCTION": 3,
            "BUTTON_ACTIVE_LOW": False,
            "BUTTON_DEBOUNCE_MS": 30,
            "BUTTON_LONG_PRESS_MS": 700,
            "BUTTON_REPEAT_INTERVAL_MS": 100,
        }
        configuration = self.load_configuration(
            "st7789-2.4inch-10pin-backpcb", overrides
        )
        for name, value in overrides.items():
            self.assertEqual(configuration[name], value)


if __name__ == "__main__":
    unittest.main()
