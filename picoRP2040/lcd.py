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



"""封装 ST7789 LCD 的硬件初始化和整帧输出。"""


from machine import Pin, SPI
import struct
import time

from config import (
    HEIGHT,
    PIN_BL,
    PIN_CS,
    PIN_DC,
    PIN_MOSI,
    PIN_RST,
    PIN_SCK,
    WIDTH,
    X_OFFSET,
    Y_OFFSET,
)


class LcdDevice:
    """封装 ST7789 的初始化、窗口设置和整帧传输。"""

    def __init__(self):
        """初始化 LCD 所需的 GPIO 与 SPI 外设。"""
        self.cs = Pin(PIN_CS, Pin.OUT, value=1)
        self.dc = Pin(PIN_DC, Pin.OUT, value=1)
        self.rst = Pin(PIN_RST, Pin.OUT, value=1)
        self.bl = Pin(PIN_BL, Pin.OUT, value=1)
        self.spi = SPI(
            0,
            baudrate=40_000_000,
            polarity=0,
            phase=0,
            sck=Pin(PIN_SCK),
            mosi=Pin(PIN_MOSI),
        )
        self._rotation = 0
        self._landscape = False

    def write_command(self, command):
        """向 LCD 写入一个控制命令。"""
        self.dc.value(0)
        self.cs.value(0)
        self.spi.write(bytes((command,)))
        self.cs.value(1)

    def write_data(self, data):
        """向 LCD 写入命令对应的数据。"""
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(data)
        self.cs.value(1)

    def command(self, command, data=None):
        """连续写入命令及其可选数据。"""
        self.write_command(command)
        if data is not None:
            self.write_data(data)

    def reset(self):
        """执行 LCD 硬件复位时序。"""
        self.rst.value(1)
        time.sleep_ms(50)
        self.rst.value(0)
        time.sleep_ms(50)
        self.rst.value(1)
        time.sleep_ms(150)

    def set_window(self, x0, y0, x1, y1):
        """设置下一次显存写入覆盖的矩形区域。"""
        self.command(0x2A, struct.pack(">HH", x0 + X_OFFSET, x1 + X_OFFSET))
        self.command(0x2B, struct.pack(">HH", y0 + Y_OFFSET, y1 + Y_OFFSET))
        self.write_command(0x2C)

    def initialize(self):
        """按照 ST7789 时序初始化当前屏幕显示方向。"""
        self.reset()
        self.command(0x01)
        time.sleep_ms(150)
        self.command(0x11)
        time.sleep_ms(120)
        self.command(0x3A, b"\x55")
        self._write_orientation()
        self.command(0x21)
        self.command(0x13)
        time.sleep_ms(10)
        self.command(0x29)
        time.sleep_ms(100)
        self.bl.value(1)

    def set_rotation(self, rotation):
        """动态设置屏幕为正常方向或旋转一百八十度。"""
        normalized = 180 if rotation == 180 else 0
        if normalized == self._rotation:
            return False
        # ST7789 MADCTL 的 MX 与 MY 同时启用即为一百八十度旋转。
        self._rotation = normalized
        self._write_orientation()
        return True

    def set_landscape(self, landscape):
        """切换 LCD 的横屏或竖屏显存扫描方向。"""
        landscape = bool(landscape)
        if landscape == self._landscape:
            return False
        self._landscape = landscape
        self._write_orientation()
        return True

    def _write_orientation(self):
        """根据画面方向与翻转角度写入 ST7789 MADCTL。"""
        if self._landscape:
            value = 0xA0 if self._rotation == 180 else 0x60
        else:
            value = 0xC0 if self._rotation == 180 else 0x00
        self.command(0x36, bytes((value,)))

    def rotation(self):
        """返回当前生效的屏幕旋转角度。"""
        return self._rotation

    def set_display_enabled(self, enabled):
        """开启或关闭 LCD 显示输出，显存内容保持不变。"""
        self.command(0x29 if enabled else 0x28)

    def show(self, frame):
        """将一帧大端 RGB565 数据完整写入 LCD。"""
        self.show_region(0, 0, WIDTH, HEIGHT, frame)

    def show_region(self, x, y, width, height, pixels):
        """将一块 RGB565 像素数据写入指定屏幕区域。"""
        self.set_window(x, y, x + width - 1, y + height - 1)
        self.dc.value(1)
        self.cs.value(0)
        self.spi.write(pixels)
        self.cs.value(1)
