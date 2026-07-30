"""Web 界面桥接层的队列、对话框和响应公共能力。"""

import queue
import time
import webbrowser
from urllib.parse import urlparse


class CommonBridgeMixin:
    """提供各业务桥接模块共享的基础操作。"""

    __slots__ = ()

    @staticmethod
    def _error(message):
        """构造统一的桥接错误响应。"""
        return {"ok": False, "message": str(message)}

    @staticmethod
    def _drain_queue(target):
        """读取队列中最新一条结果，丢弃已经过时的历史结果。"""
        latest = None
        while True:
            try:
                latest = target.get_nowait()
            except queue.Empty:
                return latest

    def _wait_worker_result(self, target, timeout=12, expected_action=None):
        """等待匹配 action 的异步结果，并忽略队列中的陈旧响应。"""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("等待设备响应超时，请确认设备连接和固件功能")
            try:
                result = target.get(timeout=remaining)
            except queue.Empty as error:
                raise RuntimeError(
                    "等待设备响应超时，请确认设备连接和固件功能"
                ) from error
            if (
                expected_action is not None
                and result.get("action") != expected_action
            ):
                continue
            if result.get("status") != "ok":
                raise RuntimeError(result.get("message") or "设备操作失败")
            return result

    def _select_file(self, file_types):
        """通过 pywebview 原生文件选择器选择单个文件。"""
        import webview

        window = getattr(self._application, "webview_window", None)
        if window is None:
            raise RuntimeError("界面窗口尚未就绪")
        dialog_enum = getattr(webview, "FileDialog", None)
        dialog_type = (
            dialog_enum.OPEN
            if dialog_enum is not None
            else webview.OPEN_DIALOG
        )
        result = window.create_file_dialog(
            dialog_type,
            allow_multiple=False,
            file_types=file_types,
        )
        return result[0] if result else None

    def _select_directory(self):
        """通过 pywebview 原生目录选择器选择单个文件夹。"""
        import webview

        window = getattr(self._application, "webview_window", None)
        if window is None:
            raise RuntimeError("界面窗口尚未就绪")
        dialog_enum = getattr(webview, "FileDialog", None)
        dialog_type = (
            dialog_enum.FOLDER
            if dialog_enum is not None
            else webview.FOLDER_DIALOG
        )
        result = window.create_file_dialog(dialog_type, allow_multiple=False)
        if isinstance(result, str):
            return result
        return result[0] if result else None

    def _open_external_url(self, payload):
        """校验 HTTP 地址并使用系统默认浏览器打开。"""
        address = str(payload.get("url") or "").strip()
        parsed = urlparse(address)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("仅允许打开有效的 http:// 或 https:// 地址")
        if not webbrowser.open_new_tab(address):
            raise RuntimeError("无法调用系统默认浏览器")
        return {"url": address}
