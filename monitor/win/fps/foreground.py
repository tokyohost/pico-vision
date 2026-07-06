"""Small Win32 helpers used to associate frame events with the foreground app."""

import ctypes
import platform
from ctypes import wintypes


def foreground_process_id():
    """Return the process id owning the foreground window, if one is available."""
    if platform.system() != "Windows":
        return None
    try:
        user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        window = user32.GetForegroundWindow()
        process_id = wintypes.DWORD()
        if window:
            user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        return int(process_id.value) or None
    except (AttributeError, OSError):
        return None
