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


"""实现 ST7789 二点四英寸十针 SPI A 款屏幕设备。"""


from .base import LcdDevice
from .profiles import LcdBacklightProfile, LcdPanelProfile, LcdPinProfile


class St7789TwoPointFourInch10PinADevice(LcdDevice):
    """适配 ST7789 二点四英寸十针 SPI A 款屏幕。"""

    panel_profile = LcdPanelProfile(
        "st7789-2.4inch-10pin-a",
        "st7789",
        "2.4inch",
        10,
        "a",
        240,
        320,
        0,
        0,
        "st7789_2_4inch_10pin_a",
    )
    # 十针裸背光由 GPIO13 控制外部低端 MOSFET，GPIO 不直接承载背光电流。
    pin_profile = LcdPinProfile(
        2,
        12,
        11,
        10,
        9,
        14,
        LcdBacklightProfile.external_low_side(13),
        baudrate=40_000_000,
        connector_pins=(
            "GND",
            "RS",
            "CS",
            "SCL",
            "SDA",
            "RESET",
            "VDD",
            "GND",
            "LED+",
            "LED-",
        ),
        signal_labels={
            "dc": "RS",
            "cs": "CS",
            "sck": "SCL",
            "mosi": "SDA",
            "rst": "RESET",
        },
        miso=15,
    )


# 工厂扫描模块时读取以下公开声明，无需维护集中式型号表。
LCD_DEVICE_CLASS = St7789TwoPointFourInch10PinADevice
LCD_DEVICE_ALIASES = (
    "st7789_2_4inch_10pin_a",
    "st7789_2_4inch_10pin",
    "st7798-2.4inch-10pin-a",
    "st7789-2.4inch-10pin",
    "st7798-2.4inch-10pin",
)
