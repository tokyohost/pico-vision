"""Web 界面的初始化数据、设置保存和连接验证接口。"""

from i18n import t, set_locale

import base64
import platform
import sys

from custom_data import (
    custom_data_panels,
    normalize_plugin_configs,
    normalize_plugin_enabled,
)

from build_info import GITHUB_REPOSITORY, MONITOR_VERSION
from qbittorrent_monitor import QbittorrentApiClient

from desktop.common.constants import APPLICATION_NAME
from desktop.common.settings import (
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
        settings["custom_data_configs"] = normalize_plugin_configs(
            settings.get("custom_data_configs"),
            legacy_intervals=settings.get("collection_task_intervals"),
        )
        settings["custom_data_enabled"] = normalize_plugin_enabled(
            settings.get("custom_data_enabled"),
        )
        qr_path = application._resource_path("assert", "fishQr.png")
        qr_data_url = ""
        if qr_path.is_file():
            qr_data_url = "data:image/png;base64," + base64.b64encode(
                qr_path.read_bytes()
            ).decode("ascii")
        qq_group_qr_path = application._resource_path("assert", "qqgroup.png")
        qq_group_qr_data_url = ""
        if qq_group_qr_path.is_file():
            qq_group_qr_data_url = "data:image/png;base64," + base64.b64encode(
                qq_group_qr_path.read_bytes()
            ).decode("ascii")
        return {
            "applicationName": APPLICATION_NAME,
            "platform": sys.platform,
            "architecture": platform.machine(),
            "version": MONITOR_VERSION,
            "settings": settings,
            "styles": application.settings.get("styles", []),
            "taskNames": COLLECTION_TASK_ZH_NAMES,
            "defaultTasks": list(DEFAULT_COLLECTION_TASK_INTERVALS),
            "customDataPanels": custom_data_panels(),
            "device": application._get_device_connection(),
            "dataDirectory": str(application.data_directory),
            "about": {
                "author": "tokyohost",
                "wechat": "hi2024FL",
                "repository": GITHUB_REPOSITORY,
                "qrDataUrl": qr_data_url,
                "qqGroup": "1109488330",
                "qqGroupQrDataUrl": qq_group_qr_data_url,
            },
        }

    def _save_developer_plan(self, payload):
        """单独保存开发者计划，不重启监控或覆盖其他未保存设置。"""
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError(t('message.developer_program_flag_must_be_a_boolean'))
        updated = dict(self._application.settings)
        updated["developer_plan"] = enabled
        self._application.settings_store.save(updated)
        self._application.settings = updated
        return {"enabled": enabled}

    def _save_settings(self, payload):
        """校验并保存 Vue 表单提交的完整设置。"""
        incoming = payload.get("settings")
        if not isinstance(incoming, dict):
            raise ValueError(t('message.valid_settings_are_required'))
        current = self._application.settings
        updated = dict(current)
        allowed = set(current)
        # 样式目录由设备查询结果维护，禁止前端旧快照覆盖刚同步的自定义样式。
        allowed.discard("styles")
        updated.update({key: incoming[key] for key in incoming if key in allowed})
        if updated.get("locale") not in ("zh-CN", "en-US"):
            raise ValueError(t("error.locale"))
        updated["port"] = str(updated.get("port") or "").strip()
        updated["websocket_client_name"] = str(
            updated.get("websocket_client_name") or ""
        ).strip()[:64]
        updated["ping_target"] = str(updated.get("ping_target") or "").strip()
        if updated.get("json_chunk_size") not in (512, 1024, 2048, 4096, 8192, 16384):
            raise ValueError(t('message.json_chunk_size_must_be_512_1024_2048_4096'))
        updated["interval"] = float(updated["interval"])
        updated["reconnect_interval"] = float(updated["reconnect_interval"])
        updated["serial_probe_interval"] = float(updated["serial_probe_interval"])
        updated["qbittorrent_interval"] = float(updated["qbittorrent_interval"])
        if updated.get("network_unit") == "Mb":
            updated["network_unit"] = "Mbps"
        if updated.get("network_unit") not in ("MB", "Mbps"):
            raise ValueError(t('message.invalid_network_rate_unit'))
        updated["idle_timeout"] = int(updated["idle_timeout"])
        updated["screen_rotation"] = int(updated["screen_rotation"])
        updated["lcd_brightness"] = int(updated["lcd_brightness"])
        updated["adaptive_transmit"] = bool(updated["adaptive_transmit"])
        updated["idle_enabled"] = bool(updated.get("idle_enabled", True))
        updated["force_usb_cdc"] = bool(updated.get("force_usb_cdc", False))
        updated["wifi_discovery_strategy"] = str(
            updated.get("wifi_discovery_strategy") or "announcement"
        ).strip().lower()
        if updated["wifi_discovery_strategy"] not in ("announcement", "scan"):
            raise ValueError(t('message.invalid_wi_fi_discovery_strategy'))
        updated["collection_task_logs"] = bool(updated["collection_task_logs"])
        updated["qbittorrent_enabled"] = bool(updated["qbittorrent_enabled"])
        updated["market_url"] = str(updated.get("market_url") or "").strip()
        if updated["market_url"] and not updated["market_url"].lower().startswith(
            ("https://", "http://")
        ):
            raise ValueError(t('message.plugin_market_url_must_start_with_http_or_https'))
        updated["http_enabled"] = bool(updated.get("http_enabled", False))
        updated["http_port"] = int(updated.get("http_port", 9876))
        if not 1 <= updated["http_port"] <= 65535:
            raise ValueError(t('message.http_management_port_must_be_between_1_and_65535'))
        updated["http_auth"] = str(updated.get("http_auth") or "").strip()
        if not updated["http_auth"]:
            raise ValueError(t('message.http_management_auth_cannot_be_empty'))
        updated["collection_task_intervals"] = normalize_collection_task_intervals(
            updated.get("collection_task_intervals")
        )
        updated["custom_data_configs"] = normalize_plugin_configs(
            updated.get("custom_data_configs"),
            legacy_intervals=current.get("collection_task_intervals"),
        )
        updated["custom_data_enabled"] = normalize_plugin_enabled(
            updated.get("custom_data_enabled"),
        )
        if updated["lcd_style"] not in style_names(updated, idle=False):
            raise ValueError(t('message.invalid_screen_style'))
        if updated["idle_enabled"] and updated["idle_style"] not in style_names(updated, idle=True):
            raise ValueError(t('message.invalid_idle_style'))
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
            or (updated["idle_enabled"] and updated["idle_timeout"] <= 0)
            or not 1 <= updated["lcd_brightness"] <= 100
        ):
            raise ValueError(t('message.check_device_name_addresses_brightness_and_intervals'))
        if updated["qbittorrent_enabled"] and not all(
            (
                updated.get("qbittorrent_address"),
                updated.get("qbittorrent_username"),
                updated.get("qbittorrent_password"),
            )
        ):
            raise ValueError(t('message.qbittorrent_requires_an_address_username_and_password'))
        self._application.settings_store.save(updated)
        self._application.settings = updated
        set_locale(updated.get("locale", "zh-CN"))
        window = getattr(self._application, "webview_window", None)
        if window is not None:
            try:
                # 与首次创建窗口一致，避免翻译字符串子类触发 .NET 类型转换异常。
                window.set_title(str(t('message.control_center').format(APPLICATION_NAME)))
            except Exception:
                # 原生窗口可能正在关闭，标题更新失败不影响语言保存和设备同步。
                pass
        if not self._application._apply_runtime_settings(wait=True):
            raise RuntimeError(t('message.monitor_is_not_running_settings_will_apply_on_next'))
        if self._application.icon is not None:
            self._application.icon.update_menu()
            self._application.icon.notify(t('ui.settings_saved_and_applied'), APPLICATION_NAME)
        self._application._schedule_http_admin_settings()
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
