"""验证 Pico 画布字形缓存的容量与淘汰策略。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
sys.path.insert(0, str(PICO_ROOT))

import canvas as canvas_module  # noqa: E402


class FakeFrameBuffer:
    """提供字形缓存测试所需的最小 FrameBuffer 替身。"""

    def __init__(self, buffer, width, height, pixel_format):
        """记录缓冲区参数，模拟固件中的原生帧缓冲对象。"""
        self.buffer = buffer
        self.width = width
        self.height = height
        self.pixel_format = pixel_format

    def fill(self, color):
        """接收背景填充操作。"""
        del color

    def fill_rect(self, x, y, width, height, color):
        """接收字形像素块填充操作。"""
        del x, y, width, height, color


class FakeFrameBufferModule:
    """模拟 MicroPython framebuf 模块的必要接口。"""

    RGB565 = 1
    FrameBuffer = FakeFrameBuffer


class CanvasGlyphCacheTest(unittest.TestCase):
    """验证字形缓存满载后不会整表清空。"""

    def test_cache_evicts_only_one_old_glyph(self):
        """达到容量上限时应保留其余热字形并加入新字形。"""
        original_framebuf = canvas_module.framebuf
        original_limit = canvas_module.MAX_GLYPH_CACHE_SIZE
        canvas_module.framebuf = FakeFrameBufferModule()
        canvas_module.MAX_GLYPH_CACHE_SIZE = 3
        try:
            drawing_canvas = canvas_module.Canvas(20, 20)
            drawing_canvas._get_scaled_glyph("A", 1, 1)
            drawing_canvas._get_scaled_glyph("B", 1, 1)
            drawing_canvas._get_scaled_glyph("C", 1, 1)
            drawing_canvas._get_scaled_glyph("D", 1, 1)

            self.assertEqual(len(drawing_canvas._glyph_cache), 3)
            self.assertNotIn(("native", "A", 1, 1), drawing_canvas._glyph_cache)
            self.assertIn(("native", "B", 1, 1), drawing_canvas._glyph_cache)
            self.assertIn(("native", "D", 1, 1), drawing_canvas._glyph_cache)
        finally:
            canvas_module.framebuf = original_framebuf
            canvas_module.MAX_GLYPH_CACHE_SIZE = original_limit


if __name__ == "__main__":
    unittest.main()
