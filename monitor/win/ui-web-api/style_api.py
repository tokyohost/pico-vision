"""Web 界面的设备屏幕样式管理接口。"""

import shutil
import tempfile
from pathlib import Path

from monitor_core.ui_helpers import (
    STYLE_PACKAGE_DIRECTORY_NAME,
    STYLE_PACKAGE_METADATA_NAME,
    extract_style_package,
    load_packaged_style_assets,
    load_style_assets,
    persist_style_package_assets,
    style_package_root,
)
from ..settings import normalize_style_catalog


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
        """读取数据插件与纯样式包提供的可选预览图和 HTML 详情。"""
        del payload
        return load_style_assets()

    @staticmethod
    def _style_package_root():
        """返回纯样式包 HTML、预览图和元数据的持久化根目录。"""
        return style_package_root()

    @staticmethod
    def _load_packaged_style_assets():
        """读取已经安装的纯样式包资源并按设备样式名称建立映射。"""
        return load_packaged_style_assets()

    def _style_upload(self, payload):
        """选择、校验并上传 Python 文件或 ZIP 样式包。"""
        path = str(payload.get("sourcePath") or "").strip()
        if not path:
            path = self._select_file(("屏幕样式 (*.py;*.zip)",))
        if not path:
            return {"cancelled": True}
        return self._upload_style_source(path, payload)

    def _upload_style_source(self, path, payload):
        """从 Python 文件或 ZIP 包中解析样式并上传到当前设备。"""
        source_path = Path(path)
        if source_path.suffix.lower() == ".py":
            return self._upload_style_python(source_path, payload)
        if source_path.suffix.lower() != ".zip":
            raise ValueError("屏幕样式仅支持 py 文件或 zip 包")
        with tempfile.TemporaryDirectory(prefix="omniwatch-style-") as temporary:
            package = self._extract_style_package(
                source_path, Path(temporary)
            )
            result = self._upload_style_python(package["style"], payload)
            self._persist_style_package_assets(
                result["styleName"], package.get("detail"), package.get("preview")
            )
            return result

    def _upload_style_python(self, path, payload):
        """校验并上传已经定位的 Python 样式文件。"""
        self._drain_queue(self._application.custom_style_upload_messages)
        validated = self._application.request_custom_style_upload(
            str(path),
            set(payload.get("existingNames") or ()),
            bool(payload.get("overwrite")),
        )
        result = self._wait_worker_result(
            self._application.custom_style_upload_messages, 90
        )
        result["filename"] = validated.filename
        result["styleName"] = validated.name
        self._application._reload_style_catalog()
        return result

    @staticmethod
    def _persist_style_package_assets(style_name, detail_path, preview_path):
        """把纯样式包的 HTML 和预览图保存到 Monitor 专用数据目录。"""
        persist_style_package_assets(style_name, detail_path, preview_path)

    @staticmethod
    def _extract_style_package(package_path, target_directory):
        """安全解压样式 ZIP，并返回清单声明的唯一 Python 样式文件。"""
        return extract_style_package(package_path, target_directory)

    def _style_delete(self, payload):
        """删除设备中的指定自定义屏幕样式。"""
        style_name = str(payload.get("name") or "").strip().lower()
        self._drain_queue(self._application.custom_style_delete_messages)
        self._application.request_custom_style_delete(
            style_name,
            str(payload.get("filename") or ""),
        )
        result = self._wait_worker_result(
            self._application.custom_style_delete_messages, 30
        )
        self._application._reload_style_catalog()
        device_styles = result.get("styles")
        if isinstance(device_styles, list):
            self._application.settings["styles"] = normalize_style_catalog(device_styles)
        if style_name and Path(style_name).name == style_name:
            asset_directory = self._style_package_root() / style_name
            if asset_directory.is_dir():
                shutil.rmtree(asset_directory)
        result["catalog"] = self._application.settings.get("styles", [])
        return result
