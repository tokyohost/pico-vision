"""实现自定义屏幕样式文件上传命令。"""

import binascii
import os

from command.base import CommandError, CommandStrategy


class UploadStyleCommand(CommandStrategy):
    """通过 Flash 临时文件分块接收、校验并保存自定义样式。"""

    name = "uploadStyle"
    max_file_size = 16 * 1024

    def __init__(self):
        """初始化当前上传会话，源码内容不在内存中累计。"""
        self._session = None

    def execute(self, params, context):
        """根据动作开始上传、追加源码块或完成样式校验。"""
        del context
        action = params.get("action")
        if action == "begin":
            return self._begin(params)
        if action == "data":
            return self._append(params)
        if action == "finish":
            return self._finish(params)
        if action == "abort":
            self._abort()
            return {"aborted": True}
        raise CommandError("INVALID_UPLOAD_ACTION")

    def _begin(self, params):
        """校验上传元数据并在 Flash 上创建空临时文件。"""
        filename = params.get("filename")
        style_name = params.get("style_name")
        size = params.get("size")
        overwrite = params.get("overwrite") is True
        if not isinstance(filename, str) or filename != "style_{}.py".format(style_name):
            raise CommandError("INVALID_STYLE_FILENAME")
        if any(not ("a" <= character <= "z" or character.isdigit() or character == "_")
               for character in str(style_name or "")):
            raise CommandError("INVALID_STYLE_NAME")
        if not isinstance(size, int) or size < 1 or size > self.max_file_size:
            raise CommandError("INVALID_STYLE_SIZE")
        directory = self._custom_style_directory()
        self._abort()
        self._remove_invalid_temporary_files(directory)
        target_path = directory + "/" + filename
        temporary_path = target_path + ".uploading"
        backup_path = target_path + ".backup"
        self._recover_backup(target_path, backup_path)
        if self._exists(target_path) and not overwrite:
            raise CommandError("STYLE_FILE_EXISTS:" + filename)
        from styles.style_plugins import custom_style_catalog, style_catalog
        matching_styles = [
            item for item in style_catalog() if item.get("name") == style_name
        ]
        if matching_styles and not overwrite:
            raise CommandError("STYLE_NAME_EXISTS:" + style_name)
        if overwrite and any(item.get("type") != "custom" for item in matching_styles):
            raise CommandError("BUILTIN_STYLE_CANNOT_OVERWRITE:" + style_name)
        if overwrite and matching_styles and not any(
                item.get("filename") == filename
                for item in custom_style_catalog()):
            raise CommandError("STYLE_OVERWRITE_MISMATCH:" + style_name)
        try:
            with open(temporary_path, "wb"):
                pass
        except OSError as error:
            raise CommandError("STYLE_TEMP_FILE_FAILED:" + str(error)) from error
        self._session = {
            "filename": filename,
            "style_name": style_name,
            "size": size,
            "written": 0,
            "sequence": 0,
            "target_path": target_path,
            "temporary_path": temporary_path,
            "backup_path": backup_path,
            "overwrite": overwrite,
        }
        return {"filename": filename, "size": size}

    def _append(self, params):
        """解码单个小数据块并立即追加到 Flash 临时文件。"""
        session = self._require_session(params)
        content = params.get("content")
        sequence = params.get("sequence")
        if sequence != session["sequence"]:
            raise CommandError("INVALID_STYLE_SEQUENCE")
        if not isinstance(content, str) or not content:
            raise CommandError("STYLE_CONTENT_REQUIRED")
        try:
            source = binascii.a2b_base64(content)
        except (ValueError, TypeError) as error:
            raise CommandError("INVALID_STYLE_CONTENT") from error
        written = session["written"] + len(source)
        if written > session["size"]:
            self._abort()
            raise CommandError("STYLE_SIZE_OVERFLOW")
        try:
            with open(session["temporary_path"], "ab") as output:
                output.write(source)
        except OSError as error:
            self._abort()
            raise CommandError("STYLE_WRITE_FAILED:" + str(error)) from error
        session["written"] = written
        session["sequence"] += 1
        return {"sequence": sequence, "written": written}

    def _finish(self, params):
        """核对接收长度，将临时文件原子改名并加载样式完成校验。"""
        session = self._require_session(params)
        if session["written"] != session["size"]:
            raise CommandError("STYLE_SIZE_MISMATCH")
        target_path = session["target_path"]
        temporary_path = session["temporary_path"]
        filename = session["filename"]
        style_name = session["style_name"]
        backup_path = session["backup_path"]
        try:
            from styles.style_plugins import create_style, release_style
            if session["overwrite"] and self._exists(target_path):
                release_style(style_name)
                self._remove(backup_path)
                os.rename(target_path, backup_path)
            os.rename(temporary_path, target_path)
            style = create_style(style_name)
            if getattr(style, "name", None) != style_name:
                raise ValueError("样式类返回了冲突的样式名")
            release_style(style_name)
            self._remove(backup_path)
        except Exception as error:
            try:
                from styles.style_plugins import release_style
                release_style(style_name)
            except Exception:
                pass
            self._remove(temporary_path)
            self._remove(target_path)
            if self._exists(backup_path):
                try:
                    os.rename(backup_path, target_path)
                except OSError:
                    pass
            self._session = None
            raise CommandError("STYLE_VALIDATION_FAILED:" + str(error)) from error
        self._session = None
        return {"filename": filename, "style_name": style_name}

    def _require_session(self, params):
        """返回匹配上传标识的活动会话，拒绝串线的数据块。"""
        session = self._session
        if session is None or params.get("upload_id") != session["filename"]:
            raise CommandError("STYLE_UPLOAD_NOT_STARTED")
        return session

    def _abort(self):
        """终止当前上传并清理未完成的 Flash 临时文件。"""
        session, self._session = self._session, None
        if session is not None:
            self._remove(session["temporary_path"])

    @classmethod
    def _remove_invalid_temporary_files(cls, directory):
        """扫描样式目录并删除以前上传遗留的无效临时文件。"""
        try:
            filenames = os.listdir(directory)
        except OSError:
            return
        for filename in filenames:
            if filename.endswith(".uploading"):
                cls._remove(directory + "/" + filename)
            elif filename.endswith(".backup"):
                backup_path = directory + "/" + filename
                cls._recover_backup(backup_path[:-7], backup_path)

    @classmethod
    def _recover_backup(cls, target_path, backup_path):
        """恢复覆盖中断留下的备份，或清理已提交覆盖的旧备份。"""
        if not cls._exists(backup_path):
            return
        if cls._exists(target_path):
            cls._remove(backup_path)
            return
        try:
            os.rename(backup_path, target_path)
        except OSError:
            pass

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
