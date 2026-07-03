"""提供 LCD 界面样式插件的注册、创建与动态加载能力。"""

import gc
import sys


_STYLE_FACTORIES = {}


def register_style(name, factory):
    """注册样式名称及其无参数工厂函数。"""
    normalized_name = _normalize_name(name)
    if not callable(factory):
        raise TypeError("样式工厂必须可调用")
    _STYLE_FACTORIES[normalized_name] = factory


def create_style(name):
    """按名称加载并创建一个样式插件实例。"""
    normalized_name = _normalize_name(name)
    if normalized_name not in _STYLE_FACTORIES:
        _load_style_module(normalized_name)
    factory = _STYLE_FACTORIES.get(normalized_name)
    if factory is None:
        raise ValueError("未找到 LCD 样式插件：{}".format(normalized_name))
    style = factory()
    for method_name in ("create_dirty_regions", "draw_visible", "draw_dirty"):
        if not callable(getattr(style, method_name, None)):
            raise TypeError("样式插件缺少方法：{}".format(method_name))
    return style


def normalize_style_name(name):
    """返回经过安全校验和规范化处理的样式名称。"""
    return _normalize_name(name)


def available_styles():
    """返回当前已经注册的样式名称元组。"""
    return tuple(sorted(_STYLE_FACTORIES))


def release_style(name):
    """释放已停用样式的工厂和模块，使其占用的堆内存可被回收。"""
    normalized_name = _normalize_name(name)
    _STYLE_FACTORIES.pop(normalized_name, None)
    sys.modules.pop("style_" + normalized_name, None)
    gc.collect()


def _normalize_name(name):
    """校验并规范化用于模块加载的样式名称。"""
    normalized_name = str(name or "default").strip().lower()
    if not normalized_name:
        normalized_name = "default"
    for character in normalized_name:
        is_ascii_letter = "a" <= character <= "z"
        if not (is_ascii_letter or character.isdigit() or character == "_"):
            raise ValueError("样式名称仅允许字母、数字和下划线")
    return normalized_name


def _load_style_module(name):
    """回收碎片内存后，按照命名约定动态导入样式模块。"""
    # 大型样式源码在首次导入时需要连续编译内存，LCD 初始化后先整理堆。
    gc.collect()
    __import__("style_" + name)
    # 及时释放导入期间产生的临时解析对象，为条带画布保留连续空间。
    gc.collect()
