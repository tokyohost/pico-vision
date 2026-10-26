"""Web 界面桥接层的队列、对话框和响应公共能力。"""

from i18n import t

import queue
import time
import webbrowser
from urllib.parse import urlparse


class CommonBridgeMixin:
    """提供各业务桥接模块共享的基础操作。"""

    __slots__ = ()

    def _copy_text(self, payload):
        """调用平台剪贴板，限制文本大小，不允许页面访问任意原生对象。"""
        text = payload.get("text")
        if not isinstance(text, str) or len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError(t('message.clipboard_content_must_be_text_smaller_than_2_mb'))
        copier = getattr(self._application, "_copy_text", None)
        if not callable(copier):
            raise RuntimeError(t('message.native_clipboard_is_not_supported_on_this_platform'))
        copier(text)
        return {"copied": True}

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
                raise RuntimeError(t('message.device_response_timed_out_check_the_connection_and_firmware'))
            try:
                result = target.get(timeout=remaining)
            except queue.Empty as error:
                raise RuntimeError(
                    t('message.device_response_timed_out_check_the_connection_and_firmware')
                ) from error
            if (
                expected_action is not None
                and result.get("action") != expected_action
            ):
                continue
            if result.get("status") != "ok":
                raise RuntimeError(result.get("message") or t('message.device_operation_failed'))
            return result

    def _select_file(self, file_types):
        """通过 pywebview 原生文件选择器选择单个文件。"""
        import webview

        window = getattr(self._application, "webview_window", None)
        if window is None:
            raise RuntimeError(t('message.the_application_window_is_not_ready'))
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
            raise RuntimeError(t('message.the_application_window_is_not_ready'))
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
            raise ValueError(t('message.only_valid_http_or_https_urls_are_allowed'))
        if not webbrowser.open_new_tab(address):
            raise RuntimeError(t('message.unable_to_open_the_default_browser'))
        return {"url": address}
