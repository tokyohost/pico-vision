"""Windows 桌面端组件。"""

from .settings import (
    DEFAULT_SETTINGS,
    STYLE_NAMES,
    TraySettingsStore,
    apply_worker_arguments,
    settings_from_arguments,
    style_label,
    style_names,
)

__all__ = (
    "DEFAULT_SETTINGS", "STYLE_NAMES", "TraySettingsStore",
    "WindowsTrayApplication", "apply_worker_arguments",
    "settings_from_arguments", "style_label", "style_names",
)


def __getattr__(name):
    """只在显式访问桌面应用时加载 Windows 原生模块。"""
    if name == "WindowsTrayApplication":
        from desktop.win.tray import WindowsTrayApplication
        return WindowsTrayApplication
    raise AttributeError(name)
