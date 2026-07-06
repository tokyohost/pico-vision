"""按照策略模式为业务代码选择可用的 Canvas 实现。"""

from canvas import Canvas as PythonCanvas
from canvasC import CanvasC, native_canvas_supported


# 在模块加载时只选择一次策略，避免每个图元都重复判断固件能力。
Canvas = CanvasC if native_canvas_supported() else PythonCanvas


def canvas_backend_name():
    """返回当前选择的画布后端名称，便于设备诊断。"""
    return "c" if Canvas is CanvasC else "python"
