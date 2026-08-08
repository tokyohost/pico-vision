"""Regression tests for device rediscovery after Windows resumes."""

import ctypes
import threading
import unittest
from unittest import mock

from monitor_core.service import MonitorService
from monitor_core.tray_commands import _dispatch_tray_command
from win.power_events import (
    PBT_APMRESUMEAUTOMATIC,
    WindowsPowerNotifications,
)
from win.tray import WindowsTrayApplication


class FakePowerApi:
    def __init__(self):
        self.register_calls = 0
        self.unregister_calls = []

    def PowerRegisterSuspendResumeNotification(
        self, flags, parameters, registration
    ):
        del parameters
        self.register_calls += 1
        self.flags = flags
        ctypes.cast(
            registration,
            ctypes.POINTER(ctypes.c_void_p),
        ).contents.value = 123
        return 0

    def PowerUnregisterSuspendResumeNotification(self, registration):
        self.unregister_calls.append(registration.value)
        return 0


class WindowsPowerResumeTest(unittest.TestCase):
    def test_native_resume_notification_invokes_callback(self):
        callback = mock.Mock()
        api = FakePowerApi()
        notifications = WindowsPowerNotifications(callback, power_api=api)

        self.assertTrue(notifications.start())
        notifications._handle_notification(None, 4, None)
        callback.assert_not_called()
        notifications._handle_notification(
            None, PBT_APMRESUMEAUTOMATIC, None
        )
        callback.assert_called_once_with()

        notifications.stop()
        self.assertEqual(api.unregister_calls, [123])

    def test_tray_forwards_resume_to_worker(self):
        application = WindowsTrayApplication.__new__(WindowsTrayApplication)
        application._write_worker_command = mock.Mock(return_value=True)

        application._handle_windows_resume()

        application._write_worker_command.assert_called_once_with(
            "RESUME_PROBE\n"
        )

    def test_resume_command_requests_forced_probe(self):
        service = mock.Mock()

        self.assertFalse(_dispatch_tray_command(service, "RESUME_PROBE"))

        service.request_resume_probe.assert_called_once_with()

    def test_resume_probe_discards_stale_connected_transport(self):
        service = MonitorService.__new__(MonitorService)
        service.client = mock.Mock()
        service.client.is_connected = True
        service.runtime_reconnect_requested = threading.Event()
        service.active_probe_requested = threading.Event()
        service.resume_probe_requested = threading.Event()
        service._stop_transmit_worker = mock.Mock()

        service.request_resume_probe()
        service._apply_pending_runtime_reconnect()

        service._stop_transmit_worker.assert_called_once_with(wait=True)
        service.client.close.assert_called_once_with()
        self.assertTrue(service.active_probe_requested.is_set())
        self.assertFalse(service.resume_probe_requested.is_set())
        self.assertFalse(service.runtime_reconnect_requested.is_set())


if __name__ == "__main__":
    unittest.main()
