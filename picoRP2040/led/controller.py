#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""以策略模式控制不同 RP2040 开发板的板载状态灯。"""


import time

from config import (
    LED_BRIGHTNESS,
    LED_DATA_PULSE_DURATION_MS,
    LED_OFF_DURATION_MS,
    LED_ON_DURATION_MS,
)


class BaseLedController:
    """定义各类状态灯共用的非阻塞状态机。"""

    def __init__(self):
        """初始化状态机的亮度、状态和切换期限。"""
        self._brightness = LED_BRIGHTNESS
        self._state = "off"
        self._deadline = time.ticks_ms()
        self._write_state("off")

    def start(self):
        """启动绿色心跳状态。"""
        self._set_state("green", LED_ON_DURATION_MS)

    def notify_data(self):
        """收到有效 JSON 后短暂显示蓝色。"""
        self._set_state("blue", LED_DATA_PULSE_DURATION_MS)

    def update(self):
        """根据系统时钟推进灯光状态，调用后立即返回。"""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._deadline) < 0:
            return
        if self._state == "off":
            self._set_state("green", LED_ON_DURATION_MS, now)
        else:
            self._set_state("off", LED_OFF_DURATION_MS, now)

    def off(self):
        """关闭状态灯。"""
        self._state = "off"
        self._write_state("off")

    def _set_state(self, state, duration_ms, now=None):
        """切换灯光状态并设置下一次状态变更时间。"""
        now = time.ticks_ms() if now is None else now
        self._state = state
        self._write_state(state)
        self._deadline = time.ticks_add(now, duration_ms)

    def _write_state(self, state):
        """向具体硬件写入状态，子类必须实现该策略方法。"""
        raise NotImplementedError


class Ws2812LedController(BaseLedController):
    """使用 WS2812 多色灯呈现绿色心跳和蓝色数据提示。"""

    def __init__(self, pin, led_count):
        """按开发板档案中的引脚和灯珠数量初始化 WS2812。"""
        import neopixel
        from machine import Pin

        self._pixels = neopixel.NeoPixel(Pin(pin), led_count)
        super().__init__()

    def _write_state(self, state):
        """将逻辑状态转换为 RGB 颜色并写入全部灯珠。"""
        if state == "green":
            color = (0, self._brightness, 0)
        elif state == "blue":
            color = (0, 0, self._brightness)
        else:
            color = (0, 0, 0)
        for index in range(len(self._pixels)):
            self._pixels[index] = color
        self._pixels.write()


class GpioLedController(BaseLedController):
    """使用普通 GPIO 单色灯呈现心跳与数据活动。"""

    def __init__(self, pin, active_high=True):
        """按指定引脚和有效电平初始化单色状态灯。"""
        from machine import Pin

        self._active_high = bool(active_high)
        self._pin = Pin(pin, Pin.OUT)
        super().__init__()

    def _write_state(self, state):
        """将非关闭状态映射为单色灯的有效电平。"""
        enabled = state != "off"
        self._pin.value(1 if enabled == self._active_high else 0)


def create_led_controller(board_profile):
    """根据开发板档案创建匹配的状态灯控制策略。"""
    if board_profile.led_driver == "ws2812":
        return Ws2812LedController(
            board_profile.led_pin, board_profile.led_count
        )
    if board_profile.led_driver == "gpio":
        return GpioLedController(
            board_profile.led_pin, board_profile.led_active_high
        )
    raise ValueError(
        "不支持的状态灯驱动：{}".format(board_profile.led_driver)
    )
