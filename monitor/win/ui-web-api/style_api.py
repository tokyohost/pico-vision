"""Web 界面的设备屏幕样式管理接口。"""

import base64
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import custom_data

from ..settings import normalize_style_catalog


LOGGER = logging.getLogger("pico-monitor.web-ui")
STYLE_PACKAGE_DIRECTORY_NAME = "stylePackages"
STYLE_PACKAGE_METADATA_NAME = "assets.json"


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
        assets.update(StyleApiMixin._load_packaged_style_assets())
        return {"assets": assets}

    @staticmethod
    def _style_package_root():
        """返回纯样式包 HTML、预览图和元数据的持久化根目录。"""
        return Path(custom_data.get_data_root()) / STYLE_PACKAGE_DIRECTORY_NAME

    @staticmethod
    def _load_packaged_style_assets():
        """读取已经安装的纯样式包资源并按设备样式名称建立映射。"""
        assets = {}
        root = StyleApiMixin._style_package_root()
        if not root.is_dir():
            return assets
        for directory in root.iterdir():
            metadata_path = directory / STYLE_PACKAGE_METADATA_NAME
            if not directory.is_dir() or not metadata_path.is_file():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                style_name = str(metadata.get("styleName") or "").strip()
                if not style_name:
                    continue
                item = {}
                preview_name = str(metadata.get("preview") or "").strip()
                if preview_name and Path(preview_name).name != preview_name:
                    raise ValueError("预览图元数据包含非法路径")
                preview_path = directory / preview_name if preview_name else None
                if preview_path and preview_path.is_file():
                    mime_type = mimetypes.guess_type(preview_path.name)[0] or "image/png"
                    encoded = base64.b64encode(preview_path.read_bytes()).decode("ascii")
                    item["previewDataUrl"] = "data:{};base64,{}".format(mime_type, encoded)
                detail_name = str(metadata.get("detail") or "").strip()
                if detail_name and Path(detail_name).name != detail_name:
                    raise ValueError("详情元数据包含非法路径")
                detail_path = directory / detail_name if detail_name else None
                if detail_path and detail_path.is_file():
                    item["detailHtml"] = detail_path.read_text(encoding="utf-8-sig")
                if item:
                    assets[style_name] = item
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                LOGGER.warning("忽略无法读取的纯样式包资源目录 %s：%s", directory, error)
        return assets

    def _style_upload(self, payload):
        """选择、校验并上传 Python 文件或 ZIP 样式包。"""
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
        root = StyleApiMixin._style_package_root()
        root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=str(root)))
        target = root / style_name
        metadata = {"styleName": style_name, "detail": "", "preview": ""}
        try:
            for field, source in (("detail", detail_path), ("preview", preview_path)):
                if source is None:
                    continue
                destination = staging / source.name
                shutil.copy2(source, destination)
                metadata[field] = destination.name
            (staging / STYLE_PACKAGE_METADATA_NAME).write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _extract_style_package(package_path, target_directory):
        """安全解压样式 ZIP，并返回清单声明的唯一 Python 样式文件。"""
        if not zipfile.is_zipfile(package_path):
            raise ValueError("选择的文件不是有效 ZIP 包")
        with zipfile.ZipFile(package_path) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 50 * 1024 * 1024:
                raise ValueError("样式 ZIP 解压后不能超过 50 MB 或 2000 个文件")
            for entry in entries:
                item_path = PurePosixPath(entry.filename.replace("\\", "/"))
                if item_path.is_absolute() or ".." in item_path.parts:
                    raise ValueError("样式 ZIP 包含不安全路径")
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("样式 ZIP 不能包含符号链接")
            manifests = [
                item for item in entries
                if not item.is_dir()
                and PurePosixPath(item.filename.replace("\\", "/")).name == "plugin.json"
            ]
            if len(manifests) != 1:
                raise ValueError("样式 ZIP 必须且只能包含一个 plugin.json")
            manifest_entry = manifests[0]
            try:
                manifest = json.loads(
                    archive.read(manifest_entry).decode("utf-8-sig")
                )
            except (UnicodeError, ValueError) as error:
                raise ValueError("plugin.json 必须是有效的 UTF-8 JSON") from error
            if manifest.get("type") != "style":
                raise ValueError("样式 ZIP 的 plugin.json type 必须为 style")
            style_name = manifest.get("style")
            if (
                not isinstance(style_name, str)
                or PurePosixPath(style_name).name != style_name
                or not style_name.lower().endswith(".py")
            ):
                raise ValueError("style 必须是样式包根目录内的 py 文件名")
            root = PurePosixPath(manifest_entry.filename.replace("\\", "/")).parent
            style_archive_path = str(root / style_name)
            names = {
                item.filename.replace("\\", "/"): item
                for item in entries if not item.is_dir()
            }
            if style_archive_path not in names:
                raise ValueError("样式 ZIP 中缺少 plugin.json 声明的 style 文件")
            # HTML 详情和预览图会持久化到 Monitor 数据目录，因此需同步校验类型和大小。
            for bind_field, path_field, extensions, maximum_size in (
                ("bind_detail", "detail", (".html", ".htm"), custom_data.CUSTOM_DATA_DETAIL_MAX_BYTES),
                ("bind_preview", "preview", (".png", ".jpg", ".jpeg", ".gif", ".webp"), custom_data.CUSTOM_DATA_PREVIEW_MAX_BYTES),
            ):
                if not manifest.get(bind_field):
                    continue
                resource_name = manifest.get(path_field)
                if (
                    not isinstance(resource_name, str)
                    or PurePosixPath(resource_name).name != resource_name
                    or not resource_name.lower().endswith(extensions)
                    or str(root / resource_name) not in names
                    or names[str(root / resource_name)].file_size > maximum_size
                ):
                    raise ValueError("{} 声明的资源无效或不存在".format(path_field))
            archive.extractall(target_directory)
        def extracted_resource(bind_field, path_field):
            """返回清单绑定资源的解压路径，未绑定时返回空值。"""
            if not manifest.get(bind_field):
                return None
            return target_directory.joinpath(*root.parts, manifest[path_field])

        package = {
            "style": target_directory.joinpath(*root.parts, style_name),
            "detail": extracted_resource("bind_detail", "detail"),
            "preview": extracted_resource("bind_preview", "preview"),
        }
        if package["detail"] is not None:
            try:
                package["detail"].read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as error:
                raise ValueError("样式详情必须是 UTF-8 编码的 HTML") from error
        if package["preview"] is not None:
            custom_data._validate_preview_content(package["preview"])
        return package

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
