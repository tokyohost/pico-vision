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



"""实现 ST7789 二点四英寸八针 SPI B 款屏幕设备。"""


from .base import LcdDevice
from .profiles import LcdBacklightProfile, LcdPanelProfile, LcdPinProfile


class St7789TwoPointFourInch8PinBDevice(LcdDevice):
    """适配 ST7789 二点四英寸八针 SPI B 款屏幕。"""

    panel_profile = LcdPanelProfile(
        "st7789-2.4inch-8pin-b",
        "st7789",
        "2.4inch",
        8,
        "b",
        240,
        320,
        0,
        0,
        "st7789_2_4inch",
    )
    pin_profile = LcdPinProfile(
        0,
        6,
        7,
        8,
        14,
        15,
        LcdBacklightProfile.pwm(26),
        connector_pins=(
            "GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BL"
        ),
    )


# 工厂扫描模块时读取以下公开声明，无需维护集中式型号表。
LCD_DEVICE_CLASS = St7789TwoPointFourInch8PinBDevice
LCD_DEVICE_ALIASES = (
    "st7789_2_4inch",
    "st7789_2_4inch_bgr",
    "st7789-2.4inch-8pin",
)
