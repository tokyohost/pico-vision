"""Configure a dedicated USB CDC interface for PV1 application traffic."""

import time

from config import (
    USB_CDC_ENUMERATION_TIMEOUT_MS,
    USB_CDC_RX_BUFFER_SIZE,
    USB_CDC_TX_BUFFER_SIZE,
)


def create_data_cdc(timeout_ms=USB_CDC_ENUMERATION_TIMEOUT_MS):
    """Keep the built-in REPL CDC and add a buffered application CDC port."""
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

    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while not cdc.is_open():
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise RuntimeError("USB_DATA_CDC_ENUMERATION_TIMEOUT")
        time.sleep_ms(20)
    return cdc
