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



"""自动发现具体 LCD 屏幕档案，并根据方案编码创建设备。"""


import os

from config import BOARD_MODEL, LCD_DEVICE_TYPE


_LCD_DEVICE_CLASSES = {}
_LCD_DEVICE_ALIASES = {}
_DISCOVERED = False
_IGNORED_MODULES = ("__init__", "base", "factory", "profiles")


def _normalize_lcd_device_type(device_type):
    """规范化屏幕方案编码，并解析屏幕模块声明的兼容别名。"""
    normalized = str(device_type or "").strip().lower()
    return _LCD_DEVICE_ALIASES.get(normalized, normalized)


def _lcd_directory():
    """返回可同时适配 MicroPython 根目录和本地测试环境的 LCD 目录。"""
    try:
        module_file = __file__
    except NameError:
        module_file = ""
    module_file = module_file.replace("\\", "/")
    if "/" in module_file:
        return module_file.rsplit("/", 1)[0]
    for directory in ("lcd", "/lcd"):
        try:
            os.listdir(directory)
            return directory
        except OSError:
            continue
    return "lcd"


def _register_lcd_module(module):
    """注册单个屏幕模块公开的设备类及全部兼容方案别名。"""
    device_class = getattr(module, "LCD_DEVICE_CLASS", None)
    if device_class is None:
        return
    panel_profile = getattr(device_class, "panel_profile", None)
    device_type = str(getattr(panel_profile, "device_type", "")).strip().lower()
    if not device_type:
        raise ValueError("LCD 屏幕模块缺少规范方案编码：{}".format(module.__name__))
    if device_type in _LCD_DEVICE_CLASSES:
        raise ValueError("LCD 屏幕方案重复：{}".format(device_type))
    _LCD_DEVICE_CLASSES[device_type] = device_class
    for alias in getattr(module, "LCD_DEVICE_ALIASES", ()):
        normalized_alias = str(alias or "").strip().lower()
        if normalized_alias:
            _LCD_DEVICE_ALIASES[normalized_alias] = device_type


def discover_lcd_profiles(force=False):
    """扫描 lcd 目录并导入所有公开 LCD_DEVICE_CLASS 的屏幕档案。"""
    global _DISCOVERED
    if _DISCOVERED and not force:
        return
    if force:
        _LCD_DEVICE_CLASSES.clear()
        _LCD_DEVICE_ALIASES.clear()
    filenames = os.listdir(_lcd_directory())
    for filename in sorted(filenames):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        module_name = filename[:-3]
        if module_name in _IGNORED_MODULES:
            continue
        module = __import__(
            "lcd." + module_name,
            None,
            None,
            ("LCD_DEVICE_CLASS", "LCD_DEVICE_ALIASES"),
        )
        _register_lcd_module(module)
    _DISCOVERED = True


def create_lcd_device(device_type=None, board_model=None):
    """根据屏幕方案与开发板型号创建使用对应脚位的设备实例。"""
    discover_lcd_profiles()
    selected_type = LCD_DEVICE_TYPE if device_type is None else device_type
    selected_board = BOARD_MODEL if board_model is None else board_model
    normalized = _normalize_lcd_device_type(selected_type)
    device_class = _LCD_DEVICE_CLASSES.get(normalized)
    if device_class is None:
        raise ValueError("未知 LCD 屏幕方案：{}".format(selected_type))
    return device_class(selected_board)


def get_lcd_panel_profile(device_type=None):
    """返回配置或指定屏幕方案的只读面板档案。"""
    discover_lcd_profiles()
    selected_type = LCD_DEVICE_TYPE if device_type is None else device_type
    normalized = _normalize_lcd_device_type(selected_type)
    device_class = _LCD_DEVICE_CLASSES.get(normalized)
    if device_class is None:
        raise ValueError("未知 LCD 屏幕方案：{}".format(selected_type))
    return device_class.panel_profile


def available_lcd_device_types():
    """自动发现并返回全部规范 LCD 屏幕方案编码。"""
    discover_lcd_profiles()
    return tuple(sorted(_LCD_DEVICE_CLASSES))
