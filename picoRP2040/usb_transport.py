"""配置专用于 PV1 应用数据传输的独立 USB CDC 接口。"""

import gc
import time

from config import (
    USB_CDC_ENUMERATION_TIMEOUT_MS,
    USB_CDC_RX_BUFFER_SIZE,
    USB_CDC_TX_BUFFER_SIZE,
)


def create_data_cdc(
    timeout_ms=USB_CDC_ENUMERATION_TIMEOUT_MS,
    wait_for_open=True,
):
    """注册应用数据 CDC，并可选择是否等待主机打开端口。"""
    try:
        import usb.device
        from usb.device.cdc import CDCInterface
    except (ImportError, AttributeError) as error:
        raise RuntimeError("MICROPYTHON_1_23_OR_NEWER_REQUIRED") from error

    cdc = CDCInterface(
        timeout=0,
        txbuf=USB_CDC_TX_BUFFER_SIZE,
        rxbuf=USB_CDC_RX_BUFFER_SIZE,
    )
    usb.device.get().init(
        cdc,
        builtin_driver=True,
        manufacturer_str="Pico Vision",
        product_str="Pico Vision REPL + Data",
    )

    if wait_for_open:
        deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
        while not cdc.is_open():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise RuntimeError("USB_DATA_CDC_ENUMERATION_TIMEOUT")
            time.sleep_ms(20)
    gc.collect()
    return cdc
