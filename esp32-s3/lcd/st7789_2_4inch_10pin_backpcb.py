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


"""实现 YD-ESP32-S3 二十八乘三十五毫米背板的 ST7789 十针屏方案。"""


from .base import LcdDevice
from .profiles import LcdBacklightProfile, LcdPanelProfile, LcdPinProfile


class St7789TwoPointFourInch10PinBackPcbDevice(LcdDevice):
    """适配 V3 背挂扩展板的二点四英寸十针屏及板载背光电路。"""

    panel_profile = LcdPanelProfile(
        "st7789-2.4inch-10pin-backpcb",
        "st7789",
        "2.4inch",
        10,
        "backpcb",
        240,
        320,
        0,
        0,
        "st7789_2_4inch_10pin_a",
    )
    # J3 的第 4～9 脚依次连接 GPIO4/5/6/7/15/16，对应复位、数据命令、
    # 片选、时钟、数据和背光 PWM；GPIO16 经 R1 驱动 Q1，低端调节 LED-。
    pin_profile = LcdPinProfile(
        2,
        7,
        15,
        6,
        5,
        4,
        LcdBacklightProfile.external_low_side(16),
        baudrate=40_000_000,
        # 按屏幕座 J1 的电气针号排列；两个接地机械固定脚不计入十针。
        connector_pins=(
            "LED-",
            "LED+",
            "GND",
            "VDD",
            "SDA",
            "CS",
            "DC",
            "SCL",
            "RST",
            "GND",
        ),
        signal_labels={
            "dc": "DC",
            "cs": "CS",
            "sck": "SCL",
            "mosi": "SDA",
            "rst": "RST",
        },
        # 屏幕不使用 MISO；显式放到 J3 第 10 脚的空闲 GPIO17，避免占用 MOSI。
        miso=17,
    )


# 工厂自动发现此声明；选择本方案时，config 同步使用 J2 的 GPIO1/2/42 三键。
LCD_DEVICE_CLASS = St7789TwoPointFourInch10PinBackPcbDevice
LCD_DEVICE_ALIASES = (
    "st7789_2_4inch_10pin_backpcb",
)
