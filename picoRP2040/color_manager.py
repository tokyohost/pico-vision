#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""集中管理不同 ST7789 屏幕模组的色彩显示参数。"""


class ColorProfile:
    """描述屏幕的反色模式及 RGB/BGR 像素顺序。"""

    def __init__(self, name, inverted, bgr):
        """使用方案名称、反色开关和颜色顺序创建色彩方案。"""
        self.name = name
        self.inverted = bool(inverted)
        self.bgr = bool(bgr)

    def inversion_command(self):
        """返回 ST7789 反色开启或关闭命令。"""
        return 0x21 if self.inverted else 0x20

    def madctl_color_bits(self):
        """返回需要合并到 MADCTL 寄存器的颜色顺序位。"""
        return 0x08 if self.bgr else 0x00


# 旧款 ST7789VW 二英寸模组需要反色，且按 RGB 顺序解释像素。
# 新款二点四英寸模组使用正常色阶；另保留 BGR 变体兼容不同批次面板。
_ST7789VW_2INCH_PROFILE = ColorProfile("st7789vw_2inch", True, False)
_COLOR_PROFILES = {
    "st7789vw_2inch": _ST7789VW_2INCH_PROFILE,
    # 保留旧名称作为兼容别名，读取后统一返回规范的芯片型号名称。
    "st7789_2inch": _ST7789VW_2INCH_PROFILE,
    "st7789_2_4inch": ColorProfile("st7789_2_4inch", False, False),
    "st7789_2_4inch_bgr": ColorProfile(
        "st7789_2_4inch_bgr", False, True
    ),
}


def get_color_profile(profile_name):
    """根据配置名称返回色彩方案，名称无效时抛出明确异常。"""
    normalized_name = str(profile_name or "").strip().lower()
    profile = _COLOR_PROFILES.get(normalized_name)
    if profile is None:
        raise ValueError("未知屏幕色彩方案：{}".format(profile_name))
    return profile


def available_color_profiles():
    """返回所有推荐使用的规范屏幕色彩方案名称。"""
    return (
        "st7789vw_2inch",
        "st7789_2_4inch",
        "st7789_2_4inch_bgr",
    )
