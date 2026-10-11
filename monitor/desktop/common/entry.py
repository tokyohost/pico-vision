"""平台桌面入口选择，后台任务与信息查询不启动 GUI。"""

import sys


def desktop_requested(arguments):
    """保持 Windows 冻结入口，Mac 冻结默认桌面，Linux 桌面显式启用。"""
    if any(getattr(arguments, name, False) for name in ("worker", "pico_info", "upgrade_pico", "update")):
        return False
    requested = getattr(arguments, "desktop", False) is True
    return requested or (sys.platform in ("win32", "darwin") and bool(getattr(sys, "frozen", False)))


def start_desktop(worker_arguments):
    """只加载当前平台桌面类，服务器和其他平台不会导入原生 GUI。"""
    if sys.platform == "win32":
        from desktop.win.tray import WindowsTrayApplication
        application = WindowsTrayApplication
    elif sys.platform == "darwin":
        from desktop.macos.application import MacOsDesktopApplication
        application = MacOsDesktopApplication
    elif sys.platform.startswith("linux"):
        from desktop.linux.application import LinuxDesktopApplication
        application = LinuxDesktopApplication
    else:
        raise RuntimeError("当前系统不支持桌面模式")
    return application.start(worker_arguments)
