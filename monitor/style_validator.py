"""校验待上传的 Pico 自定义屏幕样式源码。"""

from i18n import t

import ast
from dataclasses import dataclass
from pathlib import Path


# 样式通过小块写入 Flash，32 KB 上限兼顾复杂模板扩展空间与设备编译内存。
MAX_STYLE_FILE_SIZE = 32 * 1024
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
            raise ValueError(t('style.python_only'))
        source = style_path.read_bytes()
        if source.startswith(b"\xef\xbb\xbf"):
            raise ValueError(t('style.no_bom'))
        if not source or len(source) > MAX_STYLE_FILE_SIZE:
            raise ValueError(t('style.source_size').format(MAX_STYLE_FILE_SIZE))
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(t('style.source_encoding')) from error
        try:
            module = ast.parse(text, filename=style_path.name)
        except SyntaxError as error:
            raise ValueError(t('style.syntax_error').format(error.lineno or 0)) from error
        style_class = self._find_style_class(module)
        metadata = self._class_metadata(style_class)
        self._validate_methods(style_class)
        self._validate_registration(module, style_class.name, metadata["name"])
        expected_filename = "style_{}.py".format(metadata["name"])
        if style_path.name != expected_filename:
            raise ValueError(t('style.filename').format(expected_filename))
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
            raise ValueError(t('style.single_class'))
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
            if not isinstance(value, ast.Constant):
                continue
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in ("name", "zh_name", "type")
                    and isinstance(value.value, str)
                ):
                    metadata[target.id] = value.value.strip()
                elif (
                    isinstance(target, ast.Name)
                    and target.id == "sync_visible_frame_to_second"
                ):
                    metadata[target.id] = value.value
        if not required:
            return metadata
        if not all(metadata.get(key) for key in ("name", "zh_name", "type")):
            raise ValueError(t('style.metadata_required'))
        if metadata["type"] != "custom":
            raise ValueError(t('style.custom_type'))
        second_sync = metadata.get("sync_visible_frame_to_second", False)
        if not isinstance(second_sync, bool):
            raise ValueError(
                t('style.second_sync_boolean')
            )
        name = metadata["name"]
        if any(not ("a" <= char <= "z" or char.isdigit() or char == "_") for char in name):
            raise ValueError(t('style.invalid_name'))
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
            raise ValueError(t('style.missing_methods').format(", ".join(missing)))

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
            raise ValueError(t('style.registration').format(style_name))
