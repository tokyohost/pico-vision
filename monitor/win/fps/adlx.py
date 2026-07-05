"""Optional ctypes adapter for a small AMD ADLX FPS bridge DLL."""

import ctypes
import os
import platform
import sys
from pathlib import Path


def _find_bridge():
    configured = os.getenv("PICO_MONITOR_ADLX_BRIDGE")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    candidates = [
        Path(configured) if configured else None,
        root / "win" / "fps" / "bin" / "adlx_fps_bridge.dll",
        root / "adlx_fps_bridge.dll",
        Path(__file__).resolve().parent / "bin" / "adlx_fps_bridge.dll",
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


class AdlxBackend:
    """Read AMD's driver-provided current FPS through an optional stable C ABI bridge."""

    def __init__(self, library_path=None):
        if platform.system() != "Windows" and library_path is None:
            raise OSError("ADLX 仅支持 Windows")
        path = Path(library_path) if library_path else _find_bridge()
        if path is None:
            raise OSError("未找到 ADLX FPS 桥接库")
        self.library = ctypes.WinDLL(str(path))
        self.library.adlx_fps_initialize.restype = ctypes.c_int
        self.library.adlx_fps_current.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self.library.adlx_fps_current.restype = ctypes.c_int
        self.library.adlx_fps_shutdown.restype = None
        if self.library.adlx_fps_initialize() != 0:
            raise OSError("ADLX FPS 初始化失败")

    def start(self):
        """Match the common backend lifecycle; ADLX is initialized in the constructor."""

    def snapshot(self):
        fps = ctypes.c_int()
        if self.library.adlx_fps_current(ctypes.byref(fps)) != 0 or fps.value < 0:
            return None
        return {
            "value": float(fps.value),
            "source": "amd_adlx",
            "process_id": None,
            "process_name": "",
        }

    def close(self):
        try:
            self.library.adlx_fps_shutdown()
        except (AttributeError, OSError):
            pass
