"""提供将帧事件关联到 Windows 前台应用的辅助函数。"""

import ctypes
import platform
from ctypes import wintypes

try:
    import psutil
except ImportError:
    psutil = None


def foreground_process_id():
    """返回当前前台窗口所属的进程编号。"""
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


def related_process_ids(process_id):
    """返回前台进程及其同名父子进程组成的应用进程树编号集合。"""
    if process_id is None:
        return set()
    fallback = {int(process_id)}
    if psutil is None:
        return fallback
    try:
        process = psutil.Process(int(process_id))
        process_name = process.name().lower()
        root = process
        # Chromium 窗口有时由中间进程持有，向上找到最顶层同名进程。
        for parent in process.parents():
            if parent.name().lower() != process_name:
                break
            root = parent
        related = {int(process_id), root.pid}
        # 仅接纳同名后代，避免把启动器附带的其他后台程序算作前台应用。
        for child in root.children(recursive=True):
            try:
                if child.name().lower() == process_name:
                    related.add(child.pid)
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return related
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return fallback


def process_name(process_id):
    """返回指定进程的小写可执行文件名，读取失败时返回空字符串。"""
    if process_id is None or psutil is None:
        return ""
    try:
        return psutil.Process(int(process_id)).name().strip().lower()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return ""
