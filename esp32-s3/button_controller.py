#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""提供三枚 GPIO 按键的消抖扫描与动作事件。"""


from config import (
    BUTTON_ACTIVE_LOW,
    BUTTON_DEBOUNCE_MS,
    BUTTON_LONG_PRESS_MS,
    BUTTON_REPEAT_INTERVAL_MS,
    PIN_BUTTON_FUNCTION,
    PIN_BUTTON_STYLE_NEXT,
    PIN_BUTTON_STYLE_PREVIOUS,
)


class GpioButton:
    """封装单个 GPIO 按键的输入读取、消抖和按下事件检测。"""

    def __init__(
        self,
        pin_id,
        action,
        active_low=True,
        debounce_ms=60,
        long_press_ms=BUTTON_LONG_PRESS_MS,
        repeat_interval_ms=BUTTON_REPEAT_INTERVAL_MS,
    ):
        """按 GPIO 编号、动作名和电平规则初始化按键状态。"""
        from machine import Pin

        self.pin_id = int(pin_id)
        self.action = action
        self.active_low = bool(active_low)
        self.debounce_ms = max(0, int(debounce_ms))
        self.long_press_ms = max(1, int(long_press_ms))
        self.repeat_interval_ms = max(1, int(repeat_interval_ms))
        pull = Pin.PULL_UP if self.active_low else Pin.PULL_DOWN
        self._pin = Pin(self.pin_id, Pin.IN, pull)
        self._stable_pressed = False
        self._last_raw_pressed = self._read_pressed()
        self._last_changed_ms = 0
        self._pressed_ms = None
        self._next_repeat_ms = None

    def _read_pressed(self):
        """读取当前原始电平并转换为是否按下。"""
        value = self._pin.value()
        return value == 0 if self.active_low else value == 1

    def update(self, now_ms):
        """更新按键状态，并返回按下、长按或连发事件。"""
        raw_pressed = self._read_pressed()
        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_changed_ms = now_ms
            if self.debounce_ms > 0:
                return None
        if (
            self.debounce_ms > 0
            and _ticks_diff(now_ms, self._last_changed_ms) < self.debounce_ms
        ):
            return None
        if raw_pressed == self._stable_pressed:
            if not self._stable_pressed or self._pressed_ms is None:
                return None
            if self._next_repeat_ms is None:
                if _ticks_diff(now_ms, self._pressed_ms) < self.long_press_ms:
                    return None
                self._next_repeat_ms = _ticks_add(
                    now_ms, self.repeat_interval_ms
                )
                return self.action, "long_press"
            if _ticks_diff(now_ms, self._next_repeat_ms) >= 0:
                self._next_repeat_ms = _ticks_add(
                    now_ms, self.repeat_interval_ms
                )
                return self.action, "repeat"
            return None
        self._stable_pressed = raw_pressed
        if self._stable_pressed:
            self._pressed_ms = now_ms
            self._next_repeat_ms = None
            return self.action, "press"
        self._pressed_ms = None
        self._next_repeat_ms = None
        return None


class ButtonController:
    """统一扫描三枚后盖按键并输出样式切换或预留功能动作。"""

    def __init__(self):
        """根据配置创建上一样式、下一样式和预留功能键。"""
        self._buttons = (
            GpioButton(
                PIN_BUTTON_STYLE_PREVIOUS,
                "style_previous",
                BUTTON_ACTIVE_LOW,
                BUTTON_DEBOUNCE_MS,
                BUTTON_LONG_PRESS_MS,
                BUTTON_REPEAT_INTERVAL_MS,
            ),
            GpioButton(
                PIN_BUTTON_STYLE_NEXT,
                "style_next",
                BUTTON_ACTIVE_LOW,
                BUTTON_DEBOUNCE_MS,
                BUTTON_LONG_PRESS_MS,
                BUTTON_REPEAT_INTERVAL_MS,
            ),
            GpioButton(
                PIN_BUTTON_FUNCTION,
                "function",
                BUTTON_ACTIVE_LOW,
                BUTTON_DEBOUNCE_MS,
                BUTTON_LONG_PRESS_MS,
                BUTTON_REPEAT_INTERVAL_MS,
            ),
        )

    def update(self, now_ms):
        """扫描所有按键，并返回本轮产生的动作列表。"""
        actions = []
        for button in self._buttons:
            action = button.update(now_ms)
            if action is not None:
                actions.append(action)
        return actions


def _ticks_diff(end_ms, start_ms):
    """兼容 MicroPython 的 ticks_diff，便于主循环消抖判断。"""
    try:
        import time

        return time.ticks_diff(end_ms, start_ms)
    except AttributeError:
        return end_ms - start_ms


def _ticks_add(value_ms, delta_ms):
    """兼容 MicroPython 的 ticks_add，便于安排长按连发时间。"""
    try:
        import time

        return time.ticks_add(value_ms, delta_ms)
    except AttributeError:
        return value_ms + delta_ms
