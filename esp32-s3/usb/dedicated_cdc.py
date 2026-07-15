"""创建保留内置 REPL 的 ESP32-S3 固件原生数据 CDC。"""

from usb.native_cdc import NativeCdcUnavailable, create_native_cdc_stream


class DedicatedCdcUnavailable(RuntimeError):
    """表示当前固件不具备运行时原生 USB CDC 能力。"""


def create_dedicated_cdc(
    tx_buffer_size=1024,
    rx_buffer_size=4096,
    maximum_frame_size=None,
    manufacturer="FN Vision",
    product="ESP32-S3 REPL + Data",
):
    """取得固件启动时已经枚举的第二路 TinyUSB CDC 数据流。"""
    # 参数仅保留现有工厂调用兼容性；容量由固件编译宏确定，运行期不再重配 USB。
    del tx_buffer_size, rx_buffer_size, maximum_frame_size, manufacturer, product
    try:
        return create_native_cdc_stream()
    except NativeCdcUnavailable as error:
        raise DedicatedCdcUnavailable("ESP32_S3_NATIVE_CDC_REQUIRED") from error
