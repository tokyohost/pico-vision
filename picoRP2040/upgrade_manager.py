"""接收、校验并安装 Monitor 通过串口发送的 Pico 升级文件。"""

import os
import time

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib


STAGING_DIRECTORY = ".pico_upgrade"


class UpgradeManager:
    """管理升级会话、临时文件、摘要校验与自动重启。"""

    def __init__(self, writer):
        """保存响应函数并初始化空闲升级状态。"""
        self._write = writer
        self._version = None
        self._expected_files = 0
        self._completed_files = []
        self._file = None
        self._file_path = None
        self._file_size = 0
        self._file_written = 0
        self._file_digest = None
        self._file_hash = None

    def handle(self, command):
        """解析一条升级命令，并将明确的确认或错误写回串口。"""
        try:
            text = command.decode("ascii")
            parts = text.split(":")
            action = parts[0]
            if action == "BEGIN" and len(parts) == 3:
                self._begin(parts[1], int(parts[2]))
            elif action == "FILE" and len(parts) == 4:
                self._begin_file(parts[1], int(parts[2]), parts[3])
            elif action == "DATA" and len(parts) == 3:
                self._write_data(int(parts[1]), parts[2])
            elif action == "FILE_END" and len(parts) == 1:
                self._finish_file()
            elif action == "COMMIT" and len(parts) == 1:
                self._commit()
            elif action == "ABORT" and len(parts) == 1:
                self._abort()
            else:
                raise ValueError("BAD_COMMAND")
        except Exception as error:
            self._close_file()
            self._respond("ERR:UPGRADE:{}".format(error))

    def _begin(self, version, file_count):
        """清理遗留临时区并开始新的升级会话。"""
        if file_count <= 0:
            raise ValueError("BAD_FILE_COUNT")
        self._remove_tree(STAGING_DIRECTORY)
        self._make_directory(STAGING_DIRECTORY)
        self._version = version
        self._expected_files = file_count
        self._completed_files = []
        self._respond("ACK:UPGRADE:BEGIN:{}".format(version))

    def _begin_file(self, path, size, expected_hash):
        """校验相对路径并在升级临时区创建目标文件。"""
        if self._version is None or self._file is not None:
            raise ValueError("BAD_STATE")
        path = path.replace("\\", "/").strip("/")
        if not path or ".." in path.split("/") or path.startswith("."):
            raise ValueError("BAD_PATH")
        target = STAGING_DIRECTORY + "/" + path
        parent = target.rsplit("/", 1)[0] if "/" in target else STAGING_DIRECTORY
        self._make_directory(parent)
        self._file = open(target, "wb")
        self._file_path = path
        self._file_size = size
        self._file_written = 0
        self._file_digest = expected_hash.lower()
        self._file_hash = hashlib.sha256()
        self._respond("ACK:UPGRADE:FILE:{}".format(path))

    def _write_data(self, sequence, encoded_data):
        """解码单个数据块，写入临时文件并累计 SHA-256。"""
        if self._file is None:
            raise ValueError("BAD_STATE")
        data = binascii.a2b_base64(encoded_data)
        self._file.write(data)
        self._file_hash.update(data)
        self._file_written += len(data)
        if self._file_written > self._file_size:
            raise ValueError("FILE_TOO_LARGE")
        self._respond("ACK:UPGRADE:DATA:{}".format(sequence))

    def _finish_file(self):
        """关闭当前文件并核对长度及 SHA-256 摘要。"""
        if self._file is None:
            raise ValueError("BAD_STATE")
        path = self._file_path
        actual_hash = binascii.hexlify(self._file_hash.digest()).decode().lower()
        self._close_file()
        if self._file_written != self._file_size:
            raise ValueError("BAD_FILE_SIZE")
        if actual_hash != self._file_digest:
            raise ValueError("BAD_FILE_HASH")
        self._completed_files.append(path)
        self._respond("ACK:UPGRADE:FILE_END:{}".format(path))

    def _commit(self):
        """确认全部文件后逐个替换根目录文件并自动软重启。"""
        if self._file is not None or len(self._completed_files) != self._expected_files:
            raise ValueError("INCOMPLETE_PACKAGE")
        self._respond("PROGRESS:UPGRADE:INSTALL:0")
        for index, path in enumerate(self._completed_files):
            source = STAGING_DIRECTORY + "/" + path
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            if parent:
                self._make_directory(parent)
            try:
                os.remove(path)
            except OSError:
                pass
            os.rename(source, path)
            progress = int((index + 1) * 100 / self._expected_files)
            self._respond("PROGRESS:UPGRADE:INSTALL:{}".format(progress))
        self._remove_tree(STAGING_DIRECTORY)
        self._respond("ACK:UPGRADE:COMPLETE:{}".format(self._version))
        sleep_ms = getattr(time, "sleep_ms", None)
        if sleep_ms is not None:
            sleep_ms(200)
        else:
            time.sleep(0.2)
        try:
            import machine
            machine.reset()
        except ImportError:
            raise SystemExit("升级完成，需要重启")

    def _abort(self):
        """终止当前升级会话并删除所有临时文件。"""
        self._close_file()
        self._remove_tree(STAGING_DIRECTORY)
        self._version = None
        self._respond("ACK:UPGRADE:ABORT")

    def _close_file(self):
        """安全关闭当前临时文件。"""
        if self._file is not None:
            self._file.close()
            self._file = None

    def _respond(self, message):
        """向 Monitor 返回一条 ASCII 升级状态。"""
        self._write((message + "\n").encode("ascii"))

    @staticmethod
    def _make_directory(path):
        """递归创建目录并兼容 MicroPython 不支持 exist_ok 的情况。"""
        current = ""
        for part in path.split("/"):
            current = part if not current else current + "/" + part
            try:
                os.mkdir(current)
            except OSError:
                pass

    @classmethod
    def _remove_tree(cls, path):
        """递归删除指定升级临时目录。"""
        try:
            entries = os.listdir(path)
        except OSError:
            return
        for name in entries:
            child = path + "/" + name
            try:
                os.remove(child)
            except OSError:
                cls._remove_tree(child)
        try:
            os.rmdir(path)
        except OSError:
            pass
