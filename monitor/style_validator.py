"""校验待上传的 Pico 自定义屏幕样式源码。"""

import ast
from dataclasses import dataclass
from pathlib import Path


MAX_STYLE_FILE_SIZE = 12100
REQUIRED_STYLE_METHODS = ("create_dirty_regions", "draw_visible", "draw_dirty")


@dataclass(frozen=True)
class ValidatedStyle:
    """保存通过静态校验的样式元数据与源码。"""

    name: str
    chinese_name: str
    filename: str
    source: bytes


class StyleFileValidator:
    """以样式类为单位校验 Python 文件结构和注册信息。"""

    def validate(self, path):
        """读取样式文件并返回可用于冲突检查和上传的校验结果。"""
        style_path = Path(path)
        if style_path.suffix.lower() != ".py":
            raise ValueError("仅允许上传 .py 样式文件")
        source = style_path.read_bytes()
        if source.startswith(b"\xef\xbb\xbf"):
            raise ValueError("样式文件不能包含 UTF-8 BOM")
        if not source or len(source) > MAX_STYLE_FILE_SIZE:
            raise ValueError("样式文件大小必须在 1 至 {} 字节之间".format(MAX_STYLE_FILE_SIZE))
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("样式文件必须使用无 BOM 的 UTF-8 编码") from error
        try:
            module = ast.parse(text, filename=style_path.name)
        except SyntaxError as error:
            raise ValueError("样式文件语法错误：第 {} 行".format(error.lineno or 0)) from error
        style_class = self._find_style_class(module)
        metadata = self._class_metadata(style_class)
        self._validate_methods(style_class)
        self._validate_registration(module, style_class.name, metadata["name"])
        expected_filename = "style_{}.py".format(metadata["name"])
        if style_path.name != expected_filename:
            raise ValueError("文件名必须为 {}".format(expected_filename))
        return ValidatedStyle(
            name=metadata["name"],
            chinese_name=metadata["zh_name"],
            filename=expected_filename,
            source=source,
        )

    @staticmethod
    def _find_style_class(module):
        """查找唯一声明 custom 类型元数据的样式类。"""
        candidates = []
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            metadata = StyleFileValidator._class_metadata(node, required=False)
            if metadata.get("type") == "custom":
                candidates.append(node)
        if len(candidates) != 1:
            raise ValueError("样式文件必须且只能包含一个 type 为 custom 的样式类")
        return candidates[0]

    @staticmethod
    def _class_metadata(style_class, required=True):
        """读取样式类中的简单字符串元数据。"""
        metadata = {}
        for node in style_class.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ("name", "zh_name", "type"):
                    metadata[target.id] = value.value.strip()
        if not required:
            return metadata
        if not all(metadata.get(key) for key in ("name", "zh_name", "type")):
            raise ValueError("样式类必须声明 name、zh_name 和 type")
        if metadata["type"] != "custom":
            raise ValueError("上传样式的 type 必须为 custom")
        name = metadata["name"]
        if any(not ("a" <= char <= "z" or char.isdigit() or char == "_") for char in name):
            raise ValueError("样式名仅允许小写字母、数字和下划线")
        return metadata

    @staticmethod
    def _validate_methods(style_class):
        """校验样式类实现渲染器要求的必要方法。"""
        methods = {
            node.name for node in style_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        missing = [name for name in REQUIRED_STYLE_METHODS if name not in methods]
        if missing:
            raise ValueError("样式类缺少必要方法：{}".format("、".join(missing)))

    @staticmethod
    def _validate_registration(module, class_name, style_name):
        """确认模块注册调用使用样式类声明的相同样式名。"""
        registered_names = []
        for node in ast.walk(module):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            if not isinstance(function, ast.Name) or function.id != "register_style":
                continue
            first_argument = node.args[0]
            if isinstance(first_argument, ast.Constant) and isinstance(first_argument.value, str):
                registered_names.append(first_argument.value)
            elif (
                isinstance(first_argument, ast.Attribute)
                and first_argument.attr == "name"
                and isinstance(first_argument.value, ast.Name)
                and first_argument.value.id == class_name
            ):
                registered_names.append(style_name)
        if registered_names != [style_name]:
            raise ValueError("register_style 必须且只能注册样式名 {}".format(style_name))
