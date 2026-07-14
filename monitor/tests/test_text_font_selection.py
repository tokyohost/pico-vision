"""验证画布文字可以按单次调用选择字体。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

import canvas as canvas_module  # noqa: E402


class TextFontSelectionTest(unittest.TestCase):
    """验证默认字体、单次覆盖以及字体状态恢复。"""

    def setUp(self):
        """禁用宿主机帧缓冲并保存原模块状态。"""
        self.original_framebuf = canvas_module.framebuf
        canvas_module.framebuf = None

    def tearDown(self):
        """恢复测试前的帧缓冲模块状态。"""
        canvas_module.framebuf = self.original_framebuf

    def test_canvas_defaults_to_native_font(self):
        """新画布未指定字体时应使用原生字体。"""
        drawing_canvas = canvas_module.Canvas(20, 20)

        self.assertEqual("native", drawing_canvas._font_name)
        self.assertEqual(6, drawing_canvas.text_width("A"))

if __name__ == "__main__":
    unittest.main()
