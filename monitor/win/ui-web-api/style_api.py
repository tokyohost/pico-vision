"""Web 界面的设备屏幕样式管理接口。"""

import base64
import logging
import mimetypes

import custom_data

from ..settings import normalize_style_catalog


LOGGER = logging.getLogger("pico-monitor.web-ui")


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

    @staticmethod
    def _style_assets(payload):
        """尝试读取自定义数据插件为绑定样式提供的可选预览图和 HTML 详情。"""
        del payload
        assets = {}
        for definition in custom_data.get_manager().list_definitions():
            style_path = definition.style_path
            if not definition.bind_style or style_path is None:
                continue
            filename = style_path.name
            if not filename.startswith("style_") or not filename.lower().endswith(".py"):
                continue
            style_name = filename[6:-3].lower()
            item = {}
            preview_path = definition.preview_path
            if preview_path is not None:
                try:
                    mime_type = mimetypes.guess_type(preview_path.name)[0] or "image/png"
                    encoded = base64.b64encode(preview_path.read_bytes()).decode("ascii")
                    item["previewDataUrl"] = "data:{};base64,{}".format(mime_type, encoded)
                except (OSError, ValueError, UnicodeError) as error:
                    LOGGER.debug("忽略无法读取的自定义样式预览图：%s", error)
            detail_path = definition.detail_path
            if detail_path is not None:
                try:
                    item["detailHtml"] = detail_path.read_text(encoding="utf-8-sig")
                except (OSError, ValueError, UnicodeError) as error:
                    LOGGER.debug("忽略无法读取的自定义样式详情：%s", error)
            if item:
                assets[style_name] = item
        return {"assets": assets}

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
        result = self._wait_worker_result(
            self._application.custom_style_delete_messages, 30
        )
        self._application._reload_style_catalog()
        device_styles = result.get("styles")
        if isinstance(device_styles, list):
            self._application.settings["styles"] = normalize_style_catalog(device_styles)
        result["catalog"] = self._application.settings.get("styles", [])
        return result
