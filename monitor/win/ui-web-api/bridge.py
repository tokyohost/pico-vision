"""Vue 界面调用的统一 Python 桥接入口。"""

import logging
import threading

from .common import CommonBridgeMixin
from .custom_data_api import CustomDataApiMixin
from .device_api import DeviceApiMixin
from .log_api import LogApiMixin
from .network_api import NetworkApiMixin
from .settings_api import SettingsApiMixin
from .style_api import StyleApiMixin
from .update_api import UpdateApiMixin


LOGGER = logging.getLogger("pico-monitor.web-ui")


class WebViewBridge(
    SettingsApiMixin,
    UpdateApiMixin,
    DeviceApiMixin,
    NetworkApiMixin,
    StyleApiMixin,
    CustomDataApiMixin,
    LogApiMixin,
    CommonBridgeMixin,
):
    """向 Vue 界面公开单一 action 调用入口，不创建 HTTP 服务。"""

    __slots__ = ("_application", "_sdk_lock", "_sdk_state", "_update_states")

    def __init__(self, application):
        """保存托盘应用引用，供桥接动作复用现有业务能力。"""
        # pywebview 会递归暴露公开属性；宿主对象必须保持私有，避免扫描到
        # settings_window.native.browser.webview 并跨线程读取 WebView2 COM 属性。
        self._application = application
        self._sdk_lock = threading.Lock()
        self._sdk_state = {
            "busy": False,
            "status": "idle",
            "message": "",
            "image_path": None,
            "image": None,
            "logs": [],
        }
        self._update_states = {
            category: {
                "busy": False,
                "status": "idle",
                "message": "",
                "progress": 0,
                "logs": [],
            }
            for category in ("firmware", "sdk", "application")
        }

    def invoke(self, action, payload=None):
        """按动作名称调用受控业务方法，并返回可 JSON 序列化结果。"""
        payload = payload if isinstance(payload, dict) else {}
        handlers = {
            "app.bootstrap": self._bootstrap,
            "settings.save": self._save_settings,
            "settings.verifyQbittorrent": self._verify_qbittorrent,
            "update.check": self._check_update,
            "update.install": self._install_update,
            "update.status": self._update_status,
            "device.status": self._device_status,
            "device.probe": self._probe_device,
            "device.screenshot": self._take_screenshot,
            "device.reboot": self._reboot_device,
            "device.firmware.updateLocal": self._select_and_update_firmware,
            "device.sdk.select": self._select_sdk_image,
            "device.sdk.ports": self._sdk_ports,
            "device.sdk.flash": self._start_sdk_flash,
            "device.sdk.status": self._sdk_status,
            "wifi.list": self._wifi_list,
            "wifi.connect": self._wifi_connect,
            "wifi.forget": self._wifi_forget,
            "websocket.list": self._websocket_list,
            "websocket.update": self._websocket_update,
            "style.list": self._style_list,
            "style.assets": self._style_assets,
            "style.upload": self._style_upload,
            "style.delete": self._style_delete,
            "data.list": self._custom_data_list,
            "data.import": self._custom_data_import,
            "data.importDirectory": self._custom_data_import_directory,
            "data.installDependencies": self._custom_data_install_dependencies,
            "data.activate": self._custom_data_activate,
            "data.test": self._custom_data_test,
            "data.detail": self._custom_data_detail,
            "data.syncStyle": self._custom_data_sync_style,
            "data.delete": self._custom_data_delete,
            "log.read": self._read_log,
            "log.clear": self._clear_log,
            "log.export": self._export_log,
            "system.openDataDirectory": self._open_data_directory,
        }
        handler = handlers.get(str(action))
        if handler is None:
            return self._error("不支持的界面动作：{}".format(action))
        try:
            result = handler(payload)
            if isinstance(result, dict) and "ok" in result:
                return result
            return {"ok": True, "data": result}
        except Exception as error:
            LOGGER.exception("执行界面动作失败：%s", action)
            return self._error(str(error) or "操作失败")
