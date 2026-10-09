"""保留历史导入路径，实际实现已迁入 desktop 目录。"""

import sys
from importlib import import_module

# 保持模块对象一致，让历史依赖替换和测试补丁继续作用于真实实现。
_implementation = import_module("desktop.common.settings")
# 兼容使用 spec.loader.exec_module 直接加载文件的历史调用者。
globals().update({name: value for name, value in vars(_implementation).items() if not name.startswith("__")})
sys.modules[__name__] = _implementation
