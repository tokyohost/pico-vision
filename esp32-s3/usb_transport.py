"""创建优先使用独立数据 CDC 的 ESP32-S3 USB 传输流。"""

from config import (
    MAX_JSON_SIZE,
    USB_CDC_RX_BUFFER_SIZE,
    USB_CDC_TX_BUFFER_SIZE,
    USB_DEDICATED_CDC_ENABLED,
    USB_SESSION_TIMEOUT_MS,
)
from usb.console import Esp32S3ConsoleStream
from usb.dedicated_cdc import DedicatedCdcUnavailable, create_dedicated_cdc


# 保留旧类名，兼容已经直接导入内置控制台适配器的调用方。
Esp32S3UsbStream = Esp32S3ConsoleStream


def create_usb_stream(
    input_stream=None,
    output_stream=None,
    session_timeout_ms=USB_SESSION_TIMEOUT_MS,
    dedicated_stream=None,
    enable_dedicated=USB_DEDICATED_CDC_ENABLED,
):
    """创建独立 CDC 优先、内置控制台回退的统一 USB 数据流。"""
    fallback = Esp32S3ConsoleStream(
        input_stream=input_stream,
        output_stream=output_stream,
        session_timeout_ms=session_timeout_ms,
    )

    # 显式传入控制台流通常来自桌面测试，不能在宿主机尝试重配 USB。
    should_create = (
        dedicated_stream is None
        and enable_dedicated
        and input_stream is None
        and output_stream is None
    )
    if should_create:
        try:
            dedicated_stream = create_dedicated_cdc(
                tx_buffer_size=USB_CDC_TX_BUFFER_SIZE,
                rx_buffer_size=USB_CDC_RX_BUFFER_SIZE,
                maximum_frame_size=MAX_JSON_SIZE + 64,
            )
        except DedicatedCdcUnavailable:
            dedicated_stream = None

    return dedicated_stream if dedicated_stream is not None else fallback
