"""历史 Windows Tk 界面入口；实际实现已迁入 desktop/win/ui。"""

import sys
from importlib import import_module

_implementation = import_module("desktop.win.ui.log_window")
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
sys.modules[__name__] = _implementation
