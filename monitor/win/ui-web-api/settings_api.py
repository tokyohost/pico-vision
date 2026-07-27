"""Web 界面的初始化数据、设置保存和连接验证接口。"""

import base64

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from qbittorrent_monitor import QbittorrentApiClient

from ..constants import APPLICATION_NAME
from ..settings import (
    COLLECTION_TASK_ZH_NAMES,
    DEFAULT_COLLECTION_TASK_INTERVALS,
    normalize_collection_task_intervals,
    style_names,
)


class SettingsApiMixin:
    """处理首屏初始化和应用设置相关动作。"""

    __slots__ = ()

    def _bootstrap(self, payload):
        """返回首屏所需配置、样式、任务名称和设备状态。"""
        del payload
        application = self._application
        settings = dict(application.settings)
        settings["collection_task_intervals"] = normalize_collection_task_intervals(
            settings.get("collection_task_intervals")
        )
        qr_path = application._resource_path("assert", "fishQr.png")
        qr_data_url = ""
        if qr_path.is_file():
            qr_data_url = "data:image/png;base64," + base64.b64encode(
                qr_path.read_bytes()
            ).decode("ascii")
        return {
            "applicationName": APPLICATION_NAME,
            "version": MONITOR_VERSION,
            "settings": settings,
            "styles": application.settings.get("styles", []),
            "taskNames": COLLECTION_TASK_ZH_NAMES,
            "defaultTasks": list(DEFAULT_COLLECTION_TASK_INTERVALS),
            "device": application._get_device_connection(),
            "dataDirectory": str(application.data_directory),
            "about": {
                "author": "tokyohost",
                "wechat": "hi2024FL",
                "repository": GITHUB_REPOSITORY,
                "qrDataUrl": qr_data_url,
            },
        }

    def _save_settings(self, payload):
        """校验并保存 Vue 表单提交的完整设置。"""
        incoming = payload.get("settings")
        if not isinstance(incoming, dict):
            raise ValueError("缺少有效配置")
        current = self._application.settings
        updated = dict(current)
        allowed = set(current)
        updated.update({key: incoming[key] for key in incoming if key in allowed})
        updated["port"] = str(updated.get("port") or "").strip()
        updated["websocket_client_name"] = str(
            updated.get("websocket_client_name") or ""
        ).strip()[:64]
        updated["ping_target"] = str(updated.get("ping_target") or "").strip()
        updated["interval"] = float(updated["interval"])
        updated["reconnect_interval"] = float(updated["reconnect_interval"])
        updated["serial_probe_interval"] = float(updated["serial_probe_interval"])
        updated["qbittorrent_interval"] = float(updated["qbittorrent_interval"])
        if updated.get("network_unit") == "Mb":
            updated["network_unit"] = "Mbps"
        if updated.get("network_unit") not in ("MB", "Mbps"):
            raise ValueError("网络速率单位无效")
        updated["idle_timeout"] = int(updated["idle_timeout"])
        updated["screen_rotation"] = int(updated["screen_rotation"])
        updated["lcd_brightness"] = int(updated["lcd_brightness"])
        updated["adaptive_transmit"] = bool(updated["adaptive_transmit"])
        updated["force_usb_cdc"] = bool(updated.get("force_usb_cdc", False))
        updated["collection_task_logs"] = bool(updated["collection_task_logs"])
        updated["qbittorrent_enabled"] = bool(updated["qbittorrent_enabled"])
        updated["collection_task_intervals"] = normalize_collection_task_intervals(
            updated.get("collection_task_intervals")
        )
        if updated["lcd_style"] not in style_names(updated, idle=False):
            raise ValueError("界面样式无效")
        if updated["idle_style"] not in style_names(updated, idle=True):
            raise ValueError("待机样式无效")
        intervals = (
            updated["interval"],
            updated["reconnect_interval"],
            updated["serial_probe_interval"],
            updated["qbittorrent_interval"],
        )
        if (
            not updated["websocket_client_name"]
            or not updated["ping_target"]
            or updated["interval"] < 0.3
            or min(intervals[1:]) <= 0
            or updated["idle_timeout"] <= 0
            or not 1 <= updated["lcd_brightness"] <= 100
        ):
            raise ValueError("请检查设备名称、地址、亮度和时间间隔")
        if updated["qbittorrent_enabled"] and not all(
            (
                updated.get("qbittorrent_address"),
                updated.get("qbittorrent_username"),
                updated.get("qbittorrent_password"),
            )
        ):
            raise ValueError("启用 qBittorrent 后必须填写地址、用户名和密码")
        self._application.settings = updated
        self._application.settings_store.save(updated)
        if not self._application._apply_runtime_settings(wait=True):
            raise RuntimeError("后台监控未运行，配置将在下次启动时生效")
        if self._application.icon is not None:
            self._application.icon.update_menu()
            self._application.icon.notify("配置已保存并生效", APPLICATION_NAME)
        return {"saved": True}

    def _verify_qbittorrent(self, payload):
        """验证 qBittorrent WebUI 账号配置。"""
        client = QbittorrentApiClient(
            str(payload.get("address") or "").strip(),
            str(payload.get("username") or "").strip(),
            str(payload.get("password") or ""),
        )
        client.login()
        return {"verified": True}

