"""Web 界面桥接兼容入口，具体实现位于 ui-web-api 目录。"""

from importlib import import_module

from sdk_flash import inspect_sdk_image, is_espressif_usb_port


_API = import_module(".ui-web-api", __package__)

SDK_IMAGE_FILE_TYPES = _API.SDK_IMAGE_FILE_TYPES
SDK_RELEASE_REPOSITORY = _API.SDK_RELEASE_REPOSITORY
WebUiMixin = _API.WebUiMixin
WebViewBridge = _API.WebViewBridge

__all__ = (
    "SDK_IMAGE_FILE_TYPES",
    "SDK_RELEASE_REPOSITORY",
    "WebUiMixin",
    "WebViewBridge",
)
