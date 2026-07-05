#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



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

    def blit(self, source, x, y, transparent=-1, palette=None):
        """Accept cached glyph and whole-string bitmap copies."""
        del source, x, y, transparent, palette

    def pixel(self, x, y, color):
        """Accept palette pixel writes."""
        del x, y, color

    def hline(self, x, y, width, color):
        """Accept native horizontal-line calls."""
        del x, y, width, color

    def vline(self, x, y, height, color):
        """Accept native vertical-line calls."""
        del x, y, height, color

    def poly(self, x, y, coordinates, color, fill):
        """Record a native polygon call used by grouped history columns."""
        del x, y, coordinates, color, fill
        FakeFrameBufferModule.polygon_calls += 1


class FakeFrameBufferModule:
    """模拟 MicroPython framebuf 模块的必要接口。"""

    RGB565 = 1
    MONO_HLSB = 2
    FrameBuffer = FakeFrameBuffer
    polygon_calls = 0


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
            drawing_canvas._get_scaled_glyph("A", 1)
            drawing_canvas._get_scaled_glyph("B", 1)
            drawing_canvas._get_scaled_glyph("C", 1)
            drawing_canvas._get_scaled_glyph("D", 1)

            self.assertEqual(len(drawing_canvas._glyph_cache), 3)
            self.assertNotIn(("native", "A", 1), drawing_canvas._glyph_cache)
            self.assertIn(("native", "B", 1), drawing_canvas._glyph_cache)
            self.assertIn(("native", "D", 1), drawing_canvas._glyph_cache)
        finally:
            canvas_module.framebuf = original_framebuf
            canvas_module.MAX_GLYPH_CACHE_SIZE = original_limit

    def test_whole_text_cache_reuses_bounded_bitmap(self):
        """Repeated labels should reuse one complete rendered bitmap."""
        original_framebuf = canvas_module.framebuf
        canvas_module.framebuf = FakeFrameBufferModule()
        try:
            drawing_canvas = canvas_module.Canvas(80, 20)
            drawing_canvas.set_font("screen_2inch_compact")
            drawing_canvas.text(0, 0, "CPU", 0xFFFF)
            self.assertEqual(len(drawing_canvas._text_cache), 0)
            drawing_canvas.text(0, 0, "CPU", 0xFFFF)
            cached_bytes = drawing_canvas._text_cache_bytes
            drawing_canvas.text(0, 0, "CPU", 0xFFFF)

            self.assertEqual(len(drawing_canvas._text_cache), 1)
            self.assertEqual(drawing_canvas._text_cache_bytes, cached_bytes)
            self.assertLessEqual(cached_bytes, canvas_module.MAX_TEXT_CACHE_BYTES)
            self.assertLess(cached_bytes, len("CPU") * 8 * 7 * 2)
        finally:
            canvas_module.framebuf = original_framebuf

    def test_filled_columns_group_same_color_into_polygon(self):
        """A continuous same-color history segment should use one polygon."""
        original_framebuf = canvas_module.framebuf
        canvas_module.framebuf = FakeFrameBufferModule()
        FakeFrameBufferModule.polygon_calls = 0
        try:
            drawing_canvas = canvas_module.Canvas(20, 20)
            drawing_canvas.draw_columns(
                [(1, 5, 0xFFFF), (2, 4, 0xFFFF), (3, 6, 0xFFFF)],
                bottom=10,
            )
            self.assertEqual(FakeFrameBufferModule.polygon_calls, 1)
        finally:
            canvas_module.framebuf = original_framebuf

    def test_dynamic_numeric_text_does_not_enter_bitmap_cache(self):
        """Changing metric values must not churn large bitmap allocations."""
        original_framebuf = canvas_module.framebuf
        canvas_module.framebuf = FakeFrameBufferModule()
        try:
            drawing_canvas = canvas_module.Canvas(80, 20)
            drawing_canvas.set_font("screen_2inch_compact")
            for _ in range(3):
                drawing_canvas.text(0, 0, "CPU 57%", 0xFFFF)
            self.assertEqual(len(drawing_canvas._text_cache), 0)
        finally:
            canvas_module.framebuf = original_framebuf


if __name__ == "__main__":
    unittest.main()
