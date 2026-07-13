#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""集中管理 RP2040 与 ESP32-S3 开发板的硬件差异。"""


class BoardProfile:
    """描述开发板型号及其板载状态灯硬件参数。"""

    def __init__(
        self, name, led_driver, led_pin, led_count=1, led_active_high=True
    ):
        """创建包含 LED 驱动类型、引脚和有效电平的开发板档案。"""
        self.name = name
        self.led_driver = led_driver
        self.led_pin = int(led_pin)
        self.led_count = int(led_count)
        self.led_active_high = bool(led_active_high)


_BOARD_PROFILES = {
    "rp2040_usb": BoardProfile("rp2040_usb", "ws2812", 22, 1),
    "rp2040_typec": BoardProfile("rp2040_typec", "gpio", 25, 1),
    "esp32-s3": BoardProfile("esp32-s3", "ws2812", 48, 1),
}


def register_board_profile(profile):
    """注册新的开发板档案，名称重复时拒绝覆盖已有型号。"""
    if not isinstance(profile, BoardProfile):
        raise TypeError("开发板档案必须是 BoardProfile 实例")
    normalized_name = str(profile.name or "").strip().lower()
    if not normalized_name:
        raise ValueError("开发板型号名称不能为空")
    if normalized_name in _BOARD_PROFILES:
        raise ValueError("开发板型号已存在：{}".format(normalized_name))
    profile.name = normalized_name
    _BOARD_PROFILES[normalized_name] = profile


def get_board_profile(board_model):
    """根据配置型号返回开发板档案，型号无效时抛出明确异常。"""
    normalized_name = str(board_model or "").strip().lower()
    profile = _BOARD_PROFILES.get(normalized_name)
    if profile is None:
        raise ValueError("未知开发板型号：{}".format(board_model))
    return profile


def available_board_models():
    """返回当前已经注册的全部开发板型号。"""
    return tuple(sorted(_BOARD_PROFILES))
