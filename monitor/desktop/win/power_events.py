"""Windows 系统休眠与唤醒通知适配。"""

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
    """描述 Windows 电源回调函数及其关联上下文。"""
    _fields_ = (
        ("callback", _CALLBACK_TYPE),
        ("context", wintypes.LPVOID),
    )


class WindowsPowerNotifications:
    """注册 Windows 自动恢复通知，唤醒后复用设备重探测回调。"""

    def __init__(self, on_resume, power_api=None):
        """保存恢复处理器和可替换的原生电源 API。"""
        self.on_resume = on_resume
        self.power_api = power_api
        self.registration = wintypes.HANDLE()
        self._callback = _CALLBACK_TYPE(self._handle_notification)
        self._parameters = _DeviceNotifySubscribeParameters(
            self._callback,
            None,
        )

    def _handle_notification(self, context, event_type, setting):
        """仅处理自动唤醒事件，阻止 Python 异常穿过 Win32 回调边界。"""
        del context, setting
        if event_type == PBT_APMRESUMEAUTOMATIC:
            try:
                self.on_resume()
            except Exception:
                # 原生回调边界不能传播 Python 异常，否则可能终止系统消息处理。
                LOGGER.exception("Windows 恢复后的设备重新探测请求失败")
        return 0

    def start(self):
        """注册电源通知，不支持或注册失败时返回 False。"""
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
        """释放原生电源通知注册，支持重复关闭。"""
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
