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
from .tray import WindowsTrayApplication

__all__ = (
    "DEFAULT_SETTINGS", "STYLE_NAMES", "TraySettingsStore",
    "WindowsTrayApplication", "apply_worker_arguments",
    "settings_from_arguments", "style_label", "style_names",
)
