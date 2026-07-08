"""Windows 监控日志读取与导出服务。"""

import json
import logging
import os
import subprocess
from datetime import datetime

from build_info import MONITOR_VERSION

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

    @classmethod
    def _mask_sensitive_settings(cls, value, field_name=""):
        """递归脱敏密码、令牌等敏感配置，同时保留是否已配置的信息。"""
        sensitive_names = ("password", "token", "secret", "api_key", "apikey")
        if any(name in str(field_name).lower() for name in sensitive_names):
            return "******（已配置）" if value else "未配置"
        if isinstance(value, dict):
            return {
                key: cls._mask_sensitive_settings(item, key)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._mask_sensitive_settings(item) for item in value]
        return value

    def _build_log_export_header(self):
        """生成包含导出时间、程序版本及完整脱敏配置快照的日志头。"""
        settings = self._mask_sensitive_settings(
            dict(getattr(self, "settings", {}) or {})
        )
        lines = [
            "===== OmniWatch 配置信息 =====",
            "导出时间：{}".format(datetime.now().astimezone().isoformat(timespec="seconds")),
            "Monitor 版本：{}".format(MONITOR_VERSION),
            "配置快照：",
            json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True),
            "===== 运行日志 =====",
            "",
        ]
        return "\n".join(lines).encode("utf-8")

    def _configure_error_logging(self):
        """为当前进程安装仅记录错误级别的独立日志处理器。"""
        error_log_path = self.data_directory / "pico-monitor-error.log"
        expected_path = str(error_log_path.resolve())
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if getattr(handler, "baseFilename", None) == expected_path:
                self.error_log_path = error_log_path
                return error_log_path
        handler = logging.FileHandler(error_log_path, encoding="utf-8", delay=True)
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        ))
        root_logger.addHandler(handler)
        self.error_log_path = error_log_path
        return error_log_path

    def _export_log(self, icon=None, item=None):
        """在完整配置头之后导出最近一兆字节日志，并打开文件目录。"""
        del item
        export_directory = self.data_directory / "exports"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        export_path = export_directory / "pico-monitor-{}.log".format(timestamp)
        try:
            export_directory.mkdir(parents=True, exist_ok=True)
            export_path.write_bytes(
                self._build_log_export_header() + self._read_recent_log()
            )
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
