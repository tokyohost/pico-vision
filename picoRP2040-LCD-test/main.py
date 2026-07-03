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



"""持续全屏刷新 ST7789 LCD，并通过 USB 串口统计刷新耗时。"""


import gc
import struct
import time

from machine import Pin, SPI


# LCD 分辨率和 SPI 参数。
LCD_WIDTH = 240
LCD_HEIGHT = 320
SPI_BAUDRATE = 40_000_000

# RP2040 与 ST7789 的连接引脚。
PIN_SCK = 18
PIN_MOSI = 19
PIN_CS = 17
PIN_DC = 16
PIN_RST = 20
PIN_BL = 21

# 屏幕显存坐标偏移。
X_OFFSET = 0
Y_OFFSET = 0

# 测试颜色，格式为 RGB565。
TEST_COLORS = (0xF800, 0x001F)
STRIP_HEIGHT = 40


class St7789Benchmark:
    """驱动 ST7789 并统计连续全屏写入性能。"""

    def __init__(self):
        """初始化 GPIO、SPI 和预生成测试帧。"""
        self._cs = Pin(PIN_CS, Pin.OUT, value=1)
        self._dc = Pin(PIN_DC, Pin.OUT, value=1)
        self._rst = Pin(PIN_RST, Pin.OUT, value=1)
        self._bl = Pin(PIN_BL, Pin.OUT, value=0)
        self._spi = SPI(
            0,
            baudrate=SPI_BAUDRATE,
            polarity=0,
            phase=0,
            sck=Pin(PIN_SCK),
            mosi=Pin(PIN_MOSI),
        )
        self._strips = tuple(
            self._create_solid_strip(color) for color in TEST_COLORS
        )

    @staticmethod
    def _create_solid_strip(color):
        """预生成单色 RGB565 条带，避免申请完整帧内存。"""
        pixel = bytes(((color >> 8) & 0xFF, color & 0xFF))
        return pixel * (LCD_WIDTH * STRIP_HEIGHT)

    def _write_command(self, command, data=None):
        """向 ST7789 写入命令及可选参数。"""
        self._dc.value(0)
        self._cs.value(0)
        self._spi.write(bytes((command,)))
        self._cs.value(1)
        if data is not None:
            self._dc.value(1)
            self._cs.value(0)
            self._spi.write(data)
            self._cs.value(1)

    def _reset(self):
        """执行 ST7789 硬件复位时序。"""
        self._rst.value(1)
        time.sleep_ms(50)
        self._rst.value(0)
        time.sleep_ms(50)
        self._rst.value(1)
        time.sleep_ms(150)

    def initialize(self):
        """按照 ST7789 标准时序初始化屏幕。"""
        self._reset()
        self._write_command(0x01)
        time.sleep_ms(150)
        self._write_command(0x11)
        time.sleep_ms(120)
        self._write_command(0x3A, b"\x55")
        self._write_command(0x36, b"\x00")
        self._write_command(0x21)
        self._write_command(0x13)
        time.sleep_ms(10)
        self._write_command(0x29)
        time.sleep_ms(100)
        self._bl.value(1)

    def _set_full_window(self):
        """设置下一次显存写入覆盖完整屏幕。"""
        x_end = LCD_WIDTH - 1 + X_OFFSET
        y_end = LCD_HEIGHT - 1 + Y_OFFSET
        self._write_command(
            0x2A,
            struct.pack(">HH", X_OFFSET, x_end),
        )
        self._write_command(
            0x2B,
            struct.pack(">HH", Y_OFFSET, y_end),
        )
        self._write_command(0x2C)

    def refresh(self, strip):
        """重复写入预生成条带以覆盖完整 LCD。"""
        self._set_full_window()
        self._dc.value(1)
        self._cs.value(0)
        for _ in range(LCD_HEIGHT // STRIP_HEIGHT):
            self._spi.write(strip)
        self._cs.value(1)

    def run(self):
        """不停刷新屏幕并输出单帧及累计性能统计。"""
        self.initialize()
        gc.collect()
        frame_count = 0
        total_us = 0
        minimum_us = None
        maximum_us = 0
        print("LCD_TEST:READY:{}x{}:SPI={}HZ".format(
            LCD_WIDTH,
            LCD_HEIGHT,
            SPI_BAUDRATE,
        ))

        while True:
            strip = self._strips[frame_count % len(self._strips)]
            started_us = time.ticks_us()
            self.refresh(strip)
            elapsed_us = time.ticks_diff(time.ticks_us(), started_us)

            frame_count += 1
            total_us += elapsed_us
            minimum_us = elapsed_us if minimum_us is None else min(
                minimum_us,
                elapsed_us,
            )
            maximum_us = max(maximum_us, elapsed_us)
            average_us = total_us // frame_count
            fps = 1_000_000 / elapsed_us if elapsed_us > 0 else 0
            print(
                "LCD_FRAME:{}:TIME={}US:AVG={}US:MIN={}US:MAX={}US:FPS={:.2f}".format(
                    frame_count,
                    elapsed_us,
                    average_us,
                    minimum_us,
                    maximum_us,
                    fps,
                )
            )


def main():
    """创建 LCD 基准测试并持续运行。"""
    St7789Benchmark().run()


if __name__ == "__main__":
    main()
