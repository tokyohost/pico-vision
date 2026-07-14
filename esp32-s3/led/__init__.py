#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""提供 ESP32-S3 板载 WS2812 状态灯控制入口。"""


from .controller import create_led_controller


__all__ = ("create_led_controller",)
