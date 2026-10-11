"""历史 Windows Tk 界面入口；实际实现已迁入 desktop/win/ui。"""

import sys
from importlib import import_module

_implementation = import_module("desktop.win.ui")
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
sys.modules[__name__] = _implementation

# 历史 Tk 模块也指向同一实现，保持类型身份和测试替换一致。
for _module_name in ("about_window", "custom_data_window", "custom_style_window", "device_window", "wifi_window", "websocket_clients_window", "log_window", "settings_window", "tk_support", "idea_theme"):
    sys.modules[__name__ + "." + _module_name] = import_module("desktop.win.ui." + _module_name)
