"""Windows 托盘兼容入口；实现位于 :mod:`win` 包。"""

from win import (
    DEFAULT_SETTINGS,
    STYLE_NAMES,
    TraySettingsStore,
    WindowsTrayApplication,
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
