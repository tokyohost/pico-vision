"""控制 RP2040 开发板上的 WS2812 状态灯。"""

import micropython
import neopixel
from machine import Pin, Timer

from config import (
    LED_BRIGHTNESS,
    LED_COUNT,
    LED_DATA_PULSE_DURATION_MS,
    LED_OFF_DURATION_MS,
    LED_ON_DURATION_MS,
    PIN_LED,
)


class LedController:
    """以非阻塞方式控制板载 WS2812 绿灯闪烁。"""

    def __init__(
        self,
        pin=PIN_LED,
        led_count=LED_COUNT,
        brightness=LED_BRIGHTNESS,
        on_duration_ms=LED_ON_DURATION_MS,
        off_duration_ms=LED_OFF_DURATION_MS,
        data_pulse_duration_ms=LED_DATA_PULSE_DURATION_MS,
    ):
        """初始化状态灯，并设置心跳灯与数据提示灯的时长。"""
        self._pixels = neopixel.NeoPixel(Pin(pin), led_count)
        self._brightness = brightness
        self._on_duration_ms = on_duration_ms
        self._off_duration_ms = off_duration_ms
        self._data_pulse_duration_ms = data_pulse_duration_ms
        self._state = "off"
        self._generation = 0
        self._timer = Timer()
        self._timer_callback = self._handle_timer
        self._scheduled_toggle = self._toggle
        self._write_off()

    def start(self):
        """立即点亮绿灯，并通过硬件定时器启动周期闪烁。"""
        self._timer.deinit()
        self._generation += 1
        self._state = "green"
        self._write_green()
        self._arm_timer(self._on_duration_ms)

    def blink_blue(self):
        """收到有效数据时立即闪烁一次蓝灯，并重新开始心跳周期。"""
        self._timer.deinit()
        self._generation += 1
        self._state = "blue"
        self._write_blue()
        self._arm_timer(self._data_pulse_duration_ms)

    def off(self):
        """停止闪烁并关闭状态灯。"""
        self._timer.deinit()
        self._generation += 1
        self._state = "off"
        self._write_off()

    def _toggle(self, generation):
        """在 MicroPython 调度上下文中切换灯光并设置下一段时长。"""
        if generation != self._generation:
            return

        if self._state == "off":
            self._state = "green"
            self._write_green()
            duration_ms = self._on_duration_ms
        else:
            self._state = "off"
            self._write_off()
            duration_ms = self._off_duration_ms
        self._arm_timer(duration_ms)

    def _handle_timer(self, _timer):
        """响应定时器中断，并将灯光切换安排到安全的调度上下文。"""
        micropython.schedule(self._scheduled_toggle, self._generation)

    def _arm_timer(self, duration_ms):
        """启动一次性定时器，在指定毫秒数后触发灯光切换。"""
        self._timer.init(
            period=duration_ms,
            mode=Timer.ONE_SHOT,
            callback=self._timer_callback,
        )

    def _write_off(self):
        """向灯珠写入黑色以关闭状态灯。"""
        self._pixels[0] = (0, 0, 0)
        self._pixels.write()

    def _write_green(self):
        """按照配置亮度写入绿色灯光。"""
        self._pixels[0] = (0, self._brightness, 0)
        self._pixels.write()

    def _write_blue(self):
        """按照配置亮度写入蓝色数据提示灯。"""
        self._pixels[0] = (0, 0, self._brightness)
        self._pixels.write()
