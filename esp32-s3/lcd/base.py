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



"""定义 LCD 设备的公共硬件操作和显示输出流程。"""


from machine import Pin, PWM, SPI
import struct
import time

from color_manager import get_color_profile
from config import LCD_DMA_CHUNK_SIZE, LCD_TRANSFER_BACKEND
from lcd.transfer_backend import create_lcd_transfer_backend


class LcdDevice:
    """定义 LCD 公共操作，并由具体屏幕子类提供屏幕与脚位档案。"""

    panel_profile = None
    pin_profile = None

    def __init__(self):
        """按 ESP32-S3 固定脚位初始化 GPIO、SPI 外设和屏幕档案。"""
        if self.panel_profile is None or self.pin_profile is None:
            raise ValueError("LCD 子类缺少屏幕档案或脚位档案")
        self.cs = Pin(self.pin_profile.cs, Pin.OUT, value=1)
        self.dc = Pin(self.pin_profile.dc, Pin.OUT, value=1)
        self.rst = Pin(self.pin_profile.rst, Pin.OUT, value=1)
        # 公共层只使用背光档案转换电平和占空比，不感知 BL 或 LED 正负极差异。
        backlight = self.pin_profile.backlight
        self.bl = PWM(
            Pin(backlight.control_pin, Pin.OUT, value=backlight.off_level())
        )
        self.bl.freq(1000)
        self.bl.duty_u16(backlight.duty_for_brightness(0))
        self._backlight_brightness = 100
        self._backlight_applied = False
        spi_parameters = {
            "baudrate": self.pin_profile.baudrate,
            "polarity": 0,
            "phase": 0,
            "sck": Pin(self.pin_profile.sck),
            "mosi": Pin(self.pin_profile.mosi),
        }
        # 旧版 ESP32-S3 MicroPython 会自动占用默认 MISO，显式指定可避免背光脚冲突。
        if self.pin_profile.miso is not None:
            spi_parameters["miso"] = Pin(self.pin_profile.miso)
        self.spi = SPI(self.pin_profile.spi_id, **spi_parameters)
        self._transfer_backend = create_lcd_transfer_backend(
            LCD_TRANSFER_BACKEND,
            LCD_DMA_CHUNK_SIZE,
        )
        self._rotation = 0
        self._landscape = False
        self._color_profile = get_color_profile(
            self.panel_profile.color_profile_name
        )

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
        self.command(
            0x2A,
            struct.pack(
                ">HH",
                x0 + self.panel_profile.x_offset,
                x1 + self.panel_profile.x_offset,
            ),
        )
        self.command(
            0x2B,
            struct.pack(
                ">HH",
                y0 + self.panel_profile.y_offset,
                y1 + self.panel_profile.y_offset,
            ),
        )
        self.write_command(0x2C)

    def initialize(self):
        """按照当前控制器方案初始化屏幕显示方向。"""
        self.reset()
        self.command(0x01)
        time.sleep_ms(150)
        self.command(0x11)
        time.sleep_ms(120)
        self.command(0x3A, b"\x55")
        self._write_orientation()
        self.command(self._color_profile.inversion_command())
        self.command(0x13)
        time.sleep_ms(10)
        self.command(0x29)
        time.sleep_ms(100)
        self._clear_before_first_light()
        self.set_backlight_brightness(self._backlight_brightness)

    def set_backlight_brightness(self, brightness):
        """按档案声明的 BL 或 LED 正负极方案设置背光亮度百分比。"""
        normalized = max(1, min(100, int(brightness)))
        if normalized == self._backlight_brightness and self._backlight_applied:
            return False
        self._backlight_brightness = normalized
        self.bl.duty_u16(
            self.pin_profile.backlight.duty_for_brightness(normalized)
        )
        self._backlight_applied = True
        return True

    def backlight_brightness(self):
        """返回当前 LCD 背光亮度百分比。"""
        return self._backlight_brightness

    def _clear_before_first_light(self):
        """背光点亮前先用黑色填充控制器显存。"""
        strip_height = 40
        black_strip = bytes(self.panel_profile.width * strip_height * 2)
        y = 0
        while y < self.panel_profile.height:
            height = min(strip_height, self.panel_profile.height - y)
            self.show_region(
                0,
                y,
                self.panel_profile.width,
                height,
                memoryview(black_strip)[:self.panel_profile.width * height * 2],
            )
            y += height

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
        """根据画面方向与翻转角度写入控制器扫描方向。"""
        if self._landscape:
            value = 0xA0 if self._rotation == 180 else 0x60
        else:
            value = 0xC0 if self._rotation == 180 else 0x00
        value |= self._color_profile.madctl_color_bits()
        self.command(0x36, bytes((value,)))

    def color_profile_name(self):
        """返回当前 LCD 正在使用的屏幕色彩方案名称。"""
        return self._color_profile.name

    def device_type(self):
        """返回当前 LCD 的规范硬件类型编码。"""
        return self.panel_profile.device_type

    def transfer_backend_name(self):
        """返回当前实际生效的 LCD 像素传输后端名称。"""
        return self._transfer_backend.name

    def transfer_backend_stats(self):
        """返回当前 LCD 像素传输后端的累计运行统计。"""
        return self._transfer_backend.stats()

    def rotation(self):
        """返回当前生效的屏幕旋转角度。"""
        return self._rotation

    def set_display_enabled(self, enabled):
        """开启或关闭 LCD 显示输出，显存内容保持不变。"""
        self.command(0x29 if enabled else 0x28)

    def show(self, frame):
        """将一帧大端 RGB565 数据完整写入 LCD。"""
        self.show_region(
            0, 0, self.panel_profile.width, self.panel_profile.height, frame
        )

    def show_region(self, x, y, width, height, pixels):
        """将一块 RGB565 像素数据写入指定屏幕区域。"""
        self.set_window(x, y, x + width - 1, y + height - 1)
        self.dc.value(1)
        self.cs.value(0)
        try:
            self._transfer_backend.write(self.spi, pixels)
        finally:
            self.cs.value(1)
