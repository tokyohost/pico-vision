from machine import Pin
import neopixel
import time

# 板载 WS2812 接在 GPIO22
LED_PIN = 22
NUM_LEDS = 1

np = neopixel.NeoPixel(Pin(LED_PIN), NUM_LEDS)

def set_color(r, g, b):
    """将指定 RGB 颜色写入板载 WS2812 灯珠。"""
    np[0] = (r, g, b)
    np.write()

while True:
    # 红
    set_color(50, 0, 0)
    time.sleep(0.5)

    # 绿
    set_color(0, 50, 0)
    time.sleep(0.5)

    # 蓝
    set_color(0, 0, 50)
    time.sleep(0.5)

    # 关灯
    set_color(0, 0, 0)
    time.sleep(0.5)
