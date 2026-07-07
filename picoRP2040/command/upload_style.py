"""实现自定义屏幕样式文件上传命令。"""

import binascii
import os

from command.base import CommandError, CommandStrategy


class UploadStyleCommand(CommandStrategy):
    """校验并保存 Monitor 上传的自定义样式文件。"""

    name = "uploadStyle"

    def execute(self, params, context):
        """拒绝重名文件，写入源码并通过样式加载器完成二次校验。"""
        del context
        filename = params.get("filename")
        style_name = params.get("style_name")
        content = params.get("content")
        if not isinstance(filename, str) or filename != "style_{}.py".format(style_name):
            raise CommandError("INVALID_STYLE_FILENAME")
        if not isinstance(content, str) or not content:
            raise CommandError("STYLE_CONTENT_REQUIRED")
        if any(not ("a" <= character <= "z" or character.isdigit() or character == "_")
               for character in str(style_name or "")):
            raise CommandError("INVALID_STYLE_NAME")
        directory = self._custom_style_directory()
        target_path = directory + "/" + filename
        temporary_path = target_path + ".uploading"
        if self._exists(target_path):
            raise CommandError("STYLE_FILE_EXISTS:" + filename)
        from styles.style_plugins import style_catalog
        if any(item.get("name") == style_name for item in style_catalog()):
            raise CommandError("STYLE_NAME_EXISTS:" + style_name)
        try:
            source = binascii.a2b_base64(content)
        except (ValueError, TypeError) as error:
            raise CommandError("INVALID_STYLE_CONTENT") from error
        try:
            with open(temporary_path, "wb") as output:
                output.write(source)
            os.rename(temporary_path, target_path)
            from styles.style_plugins import create_style, release_style
            style = create_style(style_name)
            if getattr(style, "name", None) != style_name:
                raise ValueError("样式类返回了冲突的样式名")
            release_style(style_name)
        except Exception as error:
            self._remove(temporary_path)
            self._remove(target_path)
            raise CommandError("STYLE_VALIDATION_FAILED:" + str(error)) from error
        return {"filename": filename, "style_name": style_name}

    @staticmethod
    def _custom_style_directory():
        """返回当前固件可用的自定义样式目录并确保目录存在。"""
        directory = "/customStyles"
        try:
            os.stat(directory)
        except OSError:
            directory = "customStyles"
            try:
                os.stat(directory)
            except OSError:
                os.mkdir(directory)
        return directory

    @staticmethod
    def _exists(path):
        """判断指定路径是否已经存在。"""
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    @staticmethod
    def _remove(path):
        """尽力删除上传失败产生的临时文件。"""
        try:
            os.remove(path)
        except OSError:
            pass


COMMAND_STRATEGY = UploadStyleCommand()
