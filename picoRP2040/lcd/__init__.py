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



"""提供 LCD 公共抽象、具体设备注册表和设备创建入口。"""


from .base import LcdDevice
from .factory import (
    available_lcd_device_types,
    create_lcd_device,
    get_lcd_panel_profile,
)
from .profiles import LcdBacklightProfile, LcdPanelProfile, LcdPinProfile


__all__ = (
    "LcdDevice",
    "LcdBacklightProfile",
    "LcdPanelProfile",
    "LcdPinProfile",
    "available_lcd_device_types",
    "create_lcd_device",
    "get_lcd_panel_profile",
)
