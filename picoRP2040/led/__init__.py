#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""提供不同 RP2040 开发板的状态灯控制策略与创建入口。"""


from .controller import create_led_controller


__all__ = ("create_led_controller",)
