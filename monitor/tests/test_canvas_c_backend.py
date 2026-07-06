"""验证 Canvas C 加速适配器的能力检测与参数转发。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
sys.path.insert(0, str(PICO_ROOT))

import canvasC  # noqa: E402


class CanvasCBackendTest(unittest.TestCase):
    """验证矩形边框粗细参数正确交给原生模块。"""

    def setUp(self):
        """创建不依赖 FrameBuffer 初始化的最小画布实例。"""
        self.canvas = canvasC.CanvasC.__new__(canvasC.CanvasC)
        self.canvas.buffer = bytearray(8 * 6 * 2)
        self.canvas.width = 8
        self.canvas.height = 6
        self.canvas.origin_x = 2
        self.canvas.origin_y = 3

    def test_draw_rect_uses_default_single_pixel_thickness(self):
        """省略粗细时应向原生模块传递一像素。"""
        native_module = mock.Mock()
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            self.canvas.draw_rect(3, 4, 5, 6, 0xFFFF)

        native_module.draw_rect.assert_called_once_with(
            self.canvas.buffer, 8, 6, 2, 3, 3, 4, 5, 6, 0xFFFF, 1
        )

    def test_draw_rect_forwards_custom_thickness(self):
        """指定粗细时应原样转发给原生模块。"""
        native_module = mock.Mock()
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            self.canvas.draw_rect(3, 4, 5, 6, 0x1234, thickness=3)

        native_module.draw_rect.assert_called_once_with(
            self.canvas.buffer, 8, 6, 2, 3, 3, 4, 5, 6, 0x1234, 3
        )


if __name__ == "__main__":
    unittest.main()
