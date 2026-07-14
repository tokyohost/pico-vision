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



"""控制 ESP32-S3 开发板的板载 WS2812 状态灯。"""


import time

from config import (
    LED_COUNT,
    LED_BRIGHTNESS,
    LED_DATA_PULSE_DURATION_MS,
    LED_OFF_DURATION_MS,
    LED_ON_DURATION_MS,
    LED_PIN,
)


class Ws2812LedController:
    """使用板载 WS2812 呈现绿色心跳和蓝色数据提示。"""

    def __init__(self, pin=LED_PIN, led_count=LED_COUNT):
        """按 ESP32-S3 固定引脚和灯珠数量初始化状态机。"""
        import neopixel
        from machine import Pin

        self._pixels = neopixel.NeoPixel(Pin(pin), led_count)
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


def create_led_controller():
    """创建 ESP32-S3 板载 WS2812 状态灯控制器。"""
    return Ws2812LedController()
