"""Windows 监控日志读取与导出服务。"""

import os
import subprocess
from datetime import datetime

from .constants import APPLICATION_NAME, LOG_EXPORT_SIZE


class LogServiceMixin:
    """为托盘应用提供独立的业务能力。"""

    @staticmethod
    def _remove_incomplete_utf8_prefix(content):
        """移除日志片段开头不完整的 UTF-8 字符，避免中文内容乱码。"""
        for offset in range(min(4, len(content) + 1)):
            try:
                content[offset:].decode("utf-8")
                return content[offset:]
            except UnicodeDecodeError as error:
                if error.start > 0:
                    return content[offset:]
        return content

    def _read_recent_log(self, maximum_size=LOG_EXPORT_SIZE):
        """读取日志末尾指定字节数，并修正可能被截断的 UTF-8 字符。"""
        if not self.log_path.exists():
            return b""
        with self.log_path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            file_size = log_file.tell()
            log_file.seek(max(0, file_size - maximum_size))
            content = log_file.read(maximum_size)
        return self._remove_incomplete_utf8_prefix(content)

    def _export_log(self, icon=None, item=None):
        """导出最近一兆字节日志，打开文件目录并返回导出路径。"""
        del item
        export_directory = self.data_directory / "exports"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        export_path = export_directory / "pico-monitor-{}.log".format(timestamp)
        try:
            export_directory.mkdir(parents=True, exist_ok=True)
            export_path.write_bytes(self._read_recent_log())
            subprocess.Popen(
                ["explorer.exe", "/select,", str(export_path)],
                creationflags=0x08000000,
            )
            if icon is not None:
                icon.notify("日志已导出：{}".format(export_path.name), APPLICATION_NAME)
            return export_path
        except OSError as error:
            if icon is not None:
                icon.notify("日志导出失败：{}".format(error), APPLICATION_NAME)
            raise
