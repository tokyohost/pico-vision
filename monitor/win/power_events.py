"""Windows suspend/resume notification integration."""

import ctypes
import logging
from ctypes import wintypes


LOGGER = logging.getLogger("pico-monitor.windows-update")

DEVICE_NOTIFY_CALLBACK = 2
PBT_APMRESUMEAUTOMATIC = 0x0012


_CALLBACK_TYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wintypes.ULONG,
    wintypes.LPVOID,
    wintypes.ULONG,
    wintypes.LPVOID,
)


class _DeviceNotifySubscribeParameters(ctypes.Structure):
    _fields_ = (
        ("callback", _CALLBACK_TYPE),
        ("context", wintypes.LPVOID),
    )


class WindowsPowerNotifications:
    """Register a callback for Windows automatic resume notifications."""

    def __init__(self, on_resume, power_api=None):
        self.on_resume = on_resume
        self.power_api = power_api
        self.registration = wintypes.HANDLE()
        self._callback = _CALLBACK_TYPE(self._handle_notification)
        self._parameters = _DeviceNotifySubscribeParameters(
            self._callback,
            None,
        )

    def _handle_notification(self, context, event_type, setting):
        del context, setting
        if event_type == PBT_APMRESUMEAUTOMATIC:
            try:
                self.on_resume()
            except Exception:
                # Never allow an application callback to unwind through a Win32 callback.
                LOGGER.exception("Windows 恢复后的设备重新探测请求失败")
        return 0

    def start(self):
        """Subscribe to power notifications; return False if unsupported."""
        if self.registration.value:
            return True
        api = self.power_api
        if api is None:
            try:
                api = ctypes.windll.powrprof
            except (AttributeError, OSError):
                return False
            self.power_api = api
        registration = wintypes.HANDLE()
        result = api.PowerRegisterSuspendResumeNotification(
            DEVICE_NOTIFY_CALLBACK,
            ctypes.byref(self._parameters),
            ctypes.byref(registration),
        )
        if result != 0:
            LOGGER.warning("注册 Windows 电源恢复通知失败：错误码=%s", result)
            return False
        self.registration = registration
        return True

    def stop(self):
        """Release the native notification registration."""
        if not self.registration.value or self.power_api is None:
            return
        try:
            result = self.power_api.PowerUnregisterSuspendResumeNotification(
                self.registration
            )
            if result != 0:
                LOGGER.warning("注销 Windows 电源恢复通知失败：错误码=%s", result)
        finally:
            self.registration = wintypes.HANDLE()
