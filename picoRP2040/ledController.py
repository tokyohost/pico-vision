"""以非阻塞状态机控制 RP2040 板载 WS2812 状态灯。"""

import time

import neopixel
from machine import Pin

from config import (
    LED_BRIGHTNESS,
    LED_COUNT,
    LED_DATA_PULSE_DURATION_MS,
    LED_OFF_DURATION_MS,
    LED_ON_DURATION_MS,
    PIN_LED,
)


class LedController:
    """管理心跳灯和数据接收提示灯，不执行任何阻塞等待。"""

    def __init__(self, pin=PIN_LED, led_count=LED_COUNT):
        """初始化灯珠驱动与状态机时间参数。"""
        self._pixels = neopixel.NeoPixel(Pin(pin), led_count)
        self._brightness = LED_BRIGHTNESS
        self._state = "off"
        self._deadline = time.ticks_ms()
        self._write((0, 0, 0))

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
        self._write((0, 0, 0))

    def _set_state(self, state, duration_ms, now=None):
        """切换灯光状态并设置下一次状态变更时间。"""
        now = time.ticks_ms() if now is None else now
        self._state = state
        if state == "green":
            color = (0, self._brightness, 0)
        elif state == "blue":
            color = (0, 0, self._brightness)
        else:
            color = (0, 0, 0)
        self._write(color)
        self._deadline = time.ticks_add(now, duration_ms)

    def _write(self, color):
        """向全部灯珠写入指定 RGB 颜色。"""
        for index in range(len(self._pixels)):
            self._pixels[index] = color
        self._pixels.write()
