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
    # 单面接触屏幕排线按 J1 第 1 脚接屏幕第 10 脚，依次反序连接。
    # 厂家屏幕 1～10 脚：GND、RS、CS、SCL、SDA、RESET、VDD、GND、LED+、LED-。
    # J1 第 5～9 脚的 PCB 网络名仍是 LCD_SDA/CS/DC/SCL/RST，
    # 实际屏幕功能却依次为 RESET/SDA/SCL/CS/RS，必须按实际功能分配 GPIO。
    # GPIO16 经 R1 驱动 Q1，低端调节 LED-；供电、地和背光无需改线。
    pin_profile = LcdPinProfile(
        2,
        5,
        6,
        7,
        4,
        15,
        LcdBacklightProfile.external_low_side(16),
        baudrate=40_000_000,
        # 按 PCB J1 第 1～10 脚记录插屏后的实际功能，不沿用 PCB 旧网络名。
        # 两个接地机械固定脚不计入十针。
        connector_pins=(
            "LED-",
            "LED+",
            "GND",
            "VDD",
            "RESET",
            "SDA",
            "SCL",
            "CS",
            "RS",
            "GND",
        ),
        signal_labels={
            "dc": "RS",
            "cs": "CS",
            "sck": "SCL",
            "mosi": "SDA",
            "rst": "RESET",
        },
        # 屏幕不使用 MISO；显式放到 J3 第 10 脚的空闲 GPIO17，避免占用 MOSI。
        miso=17,
    )


# 工厂自动发现此声明；选择本方案时，config 同步使用 J2 的 GPIO1/2/42 三键。
LCD_DEVICE_CLASS = St7789TwoPointFourInch10PinBackPcbDevice
LCD_DEVICE_ALIASES = (
    "st7789_2_4inch_10pin_backpcb",
)
