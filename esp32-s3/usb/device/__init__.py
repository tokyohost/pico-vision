"""导出运行时 USB 设备单例访问入口。"""

from . import core
from .core import get

__all__ = ("core", "get")

