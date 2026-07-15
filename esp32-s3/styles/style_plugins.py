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



"""提供 LCD 界面样式插件的注册、创建与动态加载能力。"""


import gc
import os
import sys


_STYLE_FACTORIES = {}
_STYLE_MODULES = {}


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
    if not str(getattr(style, "zh_name", "")).strip():
        raise TypeError("样式插件缺少中文名称：{}".format(normalized_name))
    if getattr(style, "type", None) not in ("builtin", "custom"):
        raise TypeError("样式插件类型必须为 builtin 或 custom：{}".format(normalized_name))
    if not isinstance(getattr(style, "idle", False), bool):
        raise TypeError("样式插件 idle 属性必须为布尔值：{}".format(normalized_name))
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


def style_catalog():
    """从各样式类声明中读取名称、中文名称和类型。"""
    catalog = list(_scan_style_directory("/styles", "builtin"))
    catalog.extend(_scan_style_directory("/customStyles", "custom"))
    return tuple(catalog)


def custom_style_catalog():
    """返回 customStyles 目录中声明为 custom 的样式清单。"""
    return _scan_style_directory("/customStyles", "custom")


def load_startup_custom_style(logger=None):
    """依次验证自定义样式，返回首个可用于启动页面的样式名称。"""
    for metadata in custom_style_catalog():
        name = metadata["name"]
        try:
            create_style(name)
            if logger:
                logger("CUSTOM_STYLE:LOAD_SUCCESS:{}\n".format(name))
            return name
        except Exception as error:
            if logger:
                logger("CUSTOM_STYLE:LOAD_FAILED:{}:{}\n".format(name, error))
    return None


def _scan_style_directory(directory, required_type):
    """扫描指定样式目录并仅返回类型匹配的有效元数据。"""
    try:
        filenames = os.listdir(directory)
    except OSError:
        directory = directory.lstrip("/")
        try:
            filenames = os.listdir(directory)
        except OSError:
            return ()
    catalog = []
    for filename in sorted(filenames):
        if not filename.startswith("style_") or not filename.endswith(".py"):
            continue
        try:
            metadata = _read_style_metadata(directory + "/" + filename)
        except (TypeError, ValueError):
            metadata = None
        if (metadata and metadata["name"] != "boot"
                and metadata["type"] == required_type):
            path = directory + "/" + filename
            metadata["filename"] = filename
            metadata["file_size"] = _file_size(path)
            catalog.append(metadata)
    return tuple(catalog)


def _file_size(path):
    """返回样式模板文件大小，读取失败时返回零。"""
    try:
        return int(os.stat(path)[6])
    except (OSError, IndexError, TypeError):
        return 0


def _read_style_metadata(path):
    """轻量读取样式类常量，避免握手阶段导入全部绘图模块。"""
    values = {}
    try:
        try:
            source = open(path, "r", encoding="utf-8")
        except TypeError:
            source = open(path, "r")
        with source:
            for line in source:
                stripped = line.strip()
                if "=" in stripped:
                    attribute, value = stripped.split("=", 1)
                    attribute = attribute.strip()
                    value = value.strip()
                    if attribute in ("name", "zh_name", "type"):
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                            values[attribute] = value[1:-1]
                    elif attribute == "idle" and value in ("True", "False"):
                        values[attribute] = value == "True"
                if len(values) == 4:
                    break
    except OSError:
        return None
    if not all(values.get(attribute) for attribute in ("name", "zh_name", "type")):
        return None
    if values["type"] not in ("builtin", "custom"):
        return None
    return {
        "name": _normalize_name(values["name"]),
        "chinese_name": values["zh_name"],
        "type": values["type"],
        "idle": bool(values.get("idle", False)),
    }


def release_style(name):
    """释放已停用样式的工厂和模块，使其占用的堆内存可被回收。"""
    normalized_name = _normalize_name(name)
    _STYLE_FACTORIES.pop(normalized_name, None)
    module_name = _STYLE_MODULES.pop(normalized_name, None)
    sys.modules.pop(module_name or "styles.style_" + normalized_name, None)
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
    custom_path = "/customStyles/style_" + name + ".py"
    try:
        os.stat(custom_path)
        custom_exists = True
    except OSError:
        try:
            os.stat(custom_path.lstrip("/"))
            custom_exists = True
        except OSError:
            custom_exists = False
    module_name = (
        "customStyles.style_" + name
        if custom_exists else "styles.style_" + name
    )
    try:
        __import__(module_name)
    except Exception:
        # 导入中断时可能已经执行 register_style，必须清掉半成品，避免下一次
        # 切换误用未完整初始化的模块，同时释放编译器留下的临时对象。
        _STYLE_FACTORIES.pop(name, None)
        sys.modules.pop(module_name, None)
        gc.collect()
        raise
    _STYLE_MODULES[name] = module_name
    # 及时释放导入期间产生的临时解析对象，为条带画布保留连续空间。
    gc.collect()
