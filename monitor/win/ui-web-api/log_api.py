"""Web 界面的日志和数据目录接口。"""

import subprocess


class LogApiMixin:
    """处理日志读取、清理、导出和数据目录打开动作。"""

    __slots__ = ()

    def _read_log(self, payload):
        """读取最近日志并按 UTF-8 解码。"""
        maximum = min(max(int(payload.get("maximum", 300000)), 1000), 1048576)
        return {
            "content": self._application._read_recent_log(maximum).decode(
                "utf-8", errors="replace"
            )
        }

    def _clear_log(self, payload):
        """清空应用运行日志。"""
        del payload
        self._application._clear_log()
        return {"cleared": True}

    def _export_log(self, payload):
        """导出包含脱敏配置快照的日志。"""
        del payload
        path = self._application._export_log(self._application.icon)
        return {"path": str(path)}

    def _open_data_directory(self, payload):
        """使用资源管理器打开用户数据目录。"""
        del payload
        self._application.data_directory.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            ["explorer.exe", str(self._application.data_directory)],
            creationflags=0x08000000,
        )
        return {"opened": True}

