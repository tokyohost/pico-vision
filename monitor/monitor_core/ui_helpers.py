"""提供 Windows 与 Linux 管理界面共用的纯数据处理能力。"""

import base64
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


LOGGER = logging.getLogger("pico-monitor.ui-helpers")
STYLE_PACKAGE_DIRECTORY_NAME = "stylePackages"
STYLE_PACKAGE_METADATA_NAME = "assets.json"
STYLE_NAMES = {
    "default": "经典概览",
    "disk": "磁盘概览",
    "diskv2": "十五盘紧凑版",
    "diskv3": "十五盘 IP 版",
    "diskv4": "十五盘趋势版",
    "horizontal_disk": "九盘横屏版",
    "horizontal_diskv2": "九盘紧凑版",
    "horizontal_disk4x": "四盘清晰版",
    "horizontal_disk4x_qb": "四盘下载版(qBittorrent)",
    "horizontal_disk6x": "六盘均衡版",
    "simple": "三盘简洁版",
    "fps_simple": "FPS 监控简约",
    "game": "游戏监控简约",
    "idle": "像素待机时钟",
}
DEFAULT_STYLE_CATALOG = [
    {
        "name": name,
        "chinese_name": chinese_name,
        "type": "builtin",
        "idle": name == "idle",
    }
    for name, chinese_name in STYLE_NAMES.items()
]


def normalize_style_catalog(catalog):
    """校验设备样式清单，并在保留全部内置样式的基础上合并自定义样式。"""
    normalized = [dict(item) for item in DEFAULT_STYLE_CATALOG]
    seen = {item["name"] for item in normalized}
    for item in catalog if isinstance(catalog, list) else ():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        chinese_name = str(item.get("chinese_name") or "").strip()
        style_type = item.get("type")
        if not name or not chinese_name or name in seen or style_type not in ("builtin", "custom"):
            continue
        normalized_item = {
            "name": name,
            "chinese_name": chinese_name,
            "type": style_type,
        }
        if isinstance(item.get("idle"), bool):
            normalized_item["idle"] = item["idle"]
        normalized.append(normalized_item)
        seen.add(name)
    return normalized


def style_package_root():
    """返回纯样式包 HTML、预览图和元数据的持久化根目录。"""
    import custom_data

    return Path(custom_data.get_data_root()) / STYLE_PACKAGE_DIRECTORY_NAME


def load_packaged_style_assets():
    """读取已经安装的纯样式包资源并按设备样式名称建立映射。"""
    assets = {}
    root = style_package_root()
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


def load_style_assets():
    """读取数据插件与纯样式包提供的可选预览图和 HTML 详情。"""
    import custom_data

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
    assets.update(load_packaged_style_assets())
    return {"assets": assets}


def persist_style_package_assets(style_name, detail_path, preview_path):
    """把纯样式包的 HTML 和预览图保存到 Monitor 专用数据目录。"""
    root = style_package_root()
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


def extract_style_package(package_path, target_directory):
    """安全解压样式 ZIP，并返回清单声明的唯一 Python 样式文件。"""
    import custom_data

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
            manifest = json.loads(archive.read(manifest_entry).decode("utf-8-sig"))
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
        # 展示资源会持久化到 Monitor 数据目录，需要在解压前限制类型和大小。
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


def merge_wifi_networks(networks, wifi_status):
    """合并扫描结果与设备已保存网络，并标记当前连接状态。"""
    wifi_status = wifi_status if isinstance(wifi_status, dict) else {}
    saved_ssid = wifi_status.get("ssid") or ""
    connected = bool(wifi_status.get("connected"))
    merged = {}
    for network in networks if isinstance(networks, list) else []:
        if not isinstance(network, dict) or not network.get("ssid"):
            continue
        candidate = dict(network)
        candidate["saved"] = candidate["ssid"] == saved_ssid
        candidate["connected"] = connected and candidate["saved"]
        previous = merged.get(candidate["ssid"])
        if previous is None or candidate.get("rssi", -999) > previous.get("rssi", -999):
            merged[candidate["ssid"]] = candidate
    if saved_ssid and saved_ssid not in merged:
        merged[saved_ssid] = {
            "ssid": saved_ssid,
            "rssi": wifi_status.get("rssi"),
            "security": None,
            "saved": True,
            "connected": connected,
        }
    return sorted(
        merged.values(),
        key=lambda item: (
            not item.get("connected"),
            not item.get("saved"),
            -(item.get("rssi") if isinstance(item.get("rssi"), int) else -999),
            item["ssid"].lower(),
        ),
    )


def wifi_state_label(network):
    """返回无线网络的中文连接状态标签。"""
    if network.get("connected"):
        return "已连接"
    if network.get("saved"):
        return "已保存"
    return "可用"


def wifi_security_label(security):
    """把设备安全类型编码转换为适合界面展示的文本。"""
    if security == 0:
        return "开放"
    if security is None:
        return "未知"
    return "需要密钥"
