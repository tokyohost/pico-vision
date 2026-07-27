"""Web 界面的设备屏幕样式管理接口。"""


class StyleApiMixin:
    """处理屏幕样式目录、上传和删除动作。"""

    __slots__ = ()

    def _style_list(self, payload):
        """刷新并返回设备样式目录。"""
        del payload
        self._drain_queue(self._application.custom_style_messages)
        if not self._application.request_custom_style_catalog():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.custom_style_messages, 10
        )
        self._application._reload_style_catalog()
        result["catalog"] = self._application.settings.get("styles", [])
        return result

    def _style_upload(self, payload):
        """选择、校验并上传一个自定义屏幕样式文件。"""
        path = self._select_file(("Python 样式文件 (*.py)",))
        if not path:
            return {"cancelled": True}
        self._drain_queue(self._application.custom_style_upload_messages)
        validated = self._application.request_custom_style_upload(
            path,
            set(payload.get("existingNames") or ()),
            bool(payload.get("overwrite")),
        )
        result = self._wait_worker_result(
            self._application.custom_style_upload_messages, 90
        )
        result["filename"] = validated.filename
        self._application._reload_style_catalog()
        return result

    def _style_delete(self, payload):
        """删除设备中的指定自定义屏幕样式。"""
        self._drain_queue(self._application.custom_style_delete_messages)
        self._application.request_custom_style_delete(
            str(payload.get("name") or ""),
            str(payload.get("filename") or ""),
        )
        return self._wait_worker_result(
            self._application.custom_style_delete_messages, 30
        )

