"""提供 ESP32-S3 原生 USB 设备与控制台传输组件。"""

from .dedicated_cdc import create_dedicated_cdc

__all__ = ("create_dedicated_cdc",)
