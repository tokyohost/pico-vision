"""实现自定义屏幕样式文件删除命令。"""

import os

from command.base import CommandError, CommandStrategy


class StyleDeleteCommand(CommandStrategy):
    """从设备 Flash 删除指定自定义样式并释放注册缓存。"""

    name = "style.delete"

    def execute(self, params, context):
        """校验样式身份、删除对应文件并返回更新样式目录所需的信息。"""
        del context
        style_name = params.get("style_name")
        filename = params.get("filename")
        if not isinstance(style_name, str) or not style_name:
            raise CommandError("STYLE_NAME_REQUIRED")
        if filename != "style_{}.py".format(style_name):
            raise CommandError("INVALID_STYLE_FILENAME")
        from styles.style_plugins import custom_style_catalog, release_style
        metadata = next(
            (item for item in custom_style_catalog()
             if item.get("name") == style_name and item.get("filename") == filename),
            None,
        )
        if metadata is None:
            raise CommandError("CUSTOM_STYLE_NOT_FOUND:" + style_name)
        path = self._custom_style_path(filename)
        try:
            os.remove(path)
        except OSError as error:
            raise CommandError("STYLE_DELETE_FAILED:" + str(error)) from error
        release_style(style_name)
        return {
            "filename": filename,
            "style_name": style_name,
            "styles": custom_style_catalog(),
        }

    @staticmethod
    def _custom_style_path(filename):
        """返回实际存在的自定义样式文件路径。"""
        absolute_path = "/customStyles/" + filename
        try:
            os.stat(absolute_path)
            return absolute_path
        except OSError:
            return "customStyles/" + filename

COMMAND_STRATEGY = StyleDeleteCommand()
