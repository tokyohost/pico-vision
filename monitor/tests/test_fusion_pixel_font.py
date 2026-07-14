"""验证 ESP32 使用的 Fusion Pixel 闪存字库和画布集成。"""


import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
sys.path.insert(0, str(PICO_ROOT))

import canvas as canvas_module  # noqa: E402
from font_fusion_pixel import FusionPixelFont  # noqa: E402


class CountingSource:
    """代理字库文件并记录随机定位次数。"""

    def __init__(self, source):
        """保存底层字库文件并初始化定位计数。"""
        self.source = source
        self.seek_count = 0

    def seek(self, offset):
        """记录一次定位并转发到底层文件。"""
        self.seek_count += 1
        return self.source.seek(offset)

    def read(self, size=-1):
        """从底层字库读取指定字节。"""
        return self.source.read(size)

    def close(self):
        """关闭底层字库文件。"""
        return self.source.close()


class FusionPixelFontTest(unittest.TestCase):
    """验证中文字形查询、缺字回退、缓存和比例字宽。"""

    def setUp(self):
        """使用项目内生成的 Fusion Pixel 简体中文字库。"""
        font_path = PICO_ROOT / "fonts" / "fusion_pixel_8px_zh_hans.fpf"
        self.font = FusionPixelFont((str(font_path),))

    def tearDown(self):
        """关闭测试打开的字库文件。"""
        if self.font._source is not None:
            self.font._source.close()

    def test_chinese_glyph_has_visible_pixels(self):
        """常用简体中文字应存在且包含可见像素。"""
        columns = self.font.glyph("中")
        self.assertEqual(len(columns), 8)
        self.assertTrue(any(columns))

    def test_missing_glyph_falls_back_to_question_mark(self):
        """字库未覆盖的保留码点应回退为问号。"""
        self.assertEqual(self.font.glyph("\U0010ffff"), self.font.glyph("?"))

    def test_record_cache_avoids_repeated_flash_seeks(self):
        """同一字符的宽度和字形查询不应重复随机读取闪存。"""
        source = self.font._open()
        self.font._source = CountingSource(source)

        self.font.advance("中")
        first_seek_count = self.font._source.seek_count
        self.font.glyph("中")
        self.font.advance("中")

        self.assertGreater(first_seek_count, 0)
        self.assertEqual(first_seek_count, self.font._source.seek_count)

    def test_canvas_uses_font_height_and_proportional_advance(self):
        """画布应采用十二像素字形高度和原始比例步进。"""
        drawing_canvas = canvas_module.Canvas(32, 16)
        drawing_canvas._font_name = "fusion_pixel_8px"
        drawing_canvas._font = self.font
        self.assertEqual(drawing_canvas._font_height(), 12)
        self.assertEqual(
            drawing_canvas.text_width("中A"),
            self.font.advance("中") + self.font.advance("A"),
        )


if __name__ == "__main__":
    unittest.main()
