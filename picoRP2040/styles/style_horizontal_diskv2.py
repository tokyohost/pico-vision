#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""提供原横向九磁盘仪表盘的紧凑字体版本。"""


from styles.style_horizontal_disk import HorizontalDiskStyle
from styles.style_plugins import register_style


class HorizontalDiskV2Style(HorizontalDiskStyle):
    """继承原横向磁盘布局，并使用二寸屏紧凑点阵字体。"""

    name = "horizontal_diskv2"
    zh_name = "九盘紧凑版"
    type = "builtin"
    font_name = "screen_2inch_compact"


def create_horizontal_diskv2_style():
    """创建使用紧凑字体的横向九磁盘 LCD 样式插件。"""
    return HorizontalDiskV2Style()


register_style(HorizontalDiskV2Style.name, create_horizontal_diskv2_style)
