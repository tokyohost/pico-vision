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



"""实现 ST7789VW 二英寸八针 SPI A 款屏幕设备。"""


from .base import LcdDevice
from .profiles import LcdBacklightProfile, LcdPanelProfile, LcdPinProfile


class St7789TwoInch8PinADevice(LcdDevice):
    """适配 ST7789VW 二英寸八针 SPI A 款屏幕。"""

    panel_profile = LcdPanelProfile(
        "st7789-2inch-8pin-a",
        "st7789vw",
        "2inch",
        8,
        "a",
        240,
        320,
        0,
        0,
        "st7789vw_2inch",
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
LCD_DEVICE_CLASS = St7789TwoInch8PinADevice
LCD_DEVICE_ALIASES = (
    "st7789vw-2inch-8pin-a",
    "st7789_2inch",
    "st7789vw_2inch",
)
