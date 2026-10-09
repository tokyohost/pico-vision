"""统一管理平台目录、子进程启动标志与本地文件打开行为。"""

import os
import subprocess
import sys
from pathlib import Path


def data_directory():
    """保留 Windows 数据位置，其他平台使用各自的用户数据规范。"""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PicoMonitor"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OmniWatch"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "omniwatch"


def subprocess_flags():
    """仅在 Windows 隐藏子进程控制台，POSIX 不传递 Windows 标志。"""
    return 0x08000000 if sys.platform == "win32" else 0


def open_path(path, reveal=False):
    """通过系统文件管理器打开目录或定位文件，始终使用独立参数。"""
    path = str(Path(path).resolve())
    if sys.platform == "win32":
        command = ["explorer.exe", "/select,", path] if reveal else ["explorer.exe", path]
    elif sys.platform == "darwin":
        command = ["/usr/bin/open", "-R", path] if reveal else ["/usr/bin/open", path]
    else:
        command = ["xdg-open", str(Path(path).parent) if reveal else path]
    return subprocess.Popen(command, creationflags=subprocess_flags())
