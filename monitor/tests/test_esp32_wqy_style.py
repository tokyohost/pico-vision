"""验证 ESP32-S3 文泉驿八乘十六点阵字体测试样式。"""

import sys
import unittest
from pathlib import Path


ESP32_ROOT = Path(__file__).resolve().parents[2] / "esp32-s3"
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

from styles.style_plugins import create_style  # noqa: E402
from styles.style_wqy_8x16_test import Wqy8x16TestStyle  # noqa: E402


class RecordingCanvas:
    """记录文泉驿字体测试样式发出的文字绘制调用。"""

    def __init__(self):
        """初始化文字宽度和绘制调用记录。"""
        self.width_fonts = []
        self.texts = []

    def clear(self, color):
        """忽略测试无关的背景清理颜色。"""
        del color

    def fill_rect(self, x, y, width, height, color):
        """忽略测试无关的区域背景参数。"""
        del x, y, width, height, color

    def text_width(self, value, scale=1, font_name=None):
        """记录宽度计算字体并返回稳定的测试宽度。"""
        self.width_fonts.append(font_name)
        return len(str(value)) * 8 * scale

    def text(self, x, y, value, color, scale=1, font_name=None):
        """记录文字内容、位置、缩放和字体名称。"""
        del color
        self.texts.append((x, y, str(value), scale, font_name))


class Esp32WqyStyleTest(unittest.TestCase):
    """验证 ESP32-S3 文泉驿测试样式的注册和清晰点阵路径。"""

    def test_style_metadata_and_registration(self):
        """样式应可按名称创建并默认使用文泉驿八乘十六字体。"""
        style = create_style("wqy_8x16_test")

        self.assertEqual("文泉驿清晰点阵测试", style.zh_name)
        self.assertEqual("wqy_8x16", style.font_name)
        self.assertEqual((240, 320), (style.width, style.height))
        self.assertFalse(style.landscape)

    def test_dirty_regions_fit_strip_canvas(self):
        """全部刷新区域都应适配二百四十乘四十的条带画布。"""
        regions = Wqy8x16TestStyle.create_dirty_regions()

        self.assertEqual(8, len(regions))
        for _key, _x, _y, width, height in regions:
            self.assertLessEqual(width * height, 240 * 40)

    def test_all_text_uses_wqy_integer_pixel_font(self):
        """全部文字和宽度计算都应只使用文泉驿点阵字体。"""
        canvas = RecordingCanvas()

        Wqy8x16TestStyle.draw_visible(canvas, {})

        self.assertTrue(canvas.texts)
        self.assertTrue(canvas.width_fonts)
        self.assertEqual({"wqy_8x16"}, set(canvas.width_fonts))
        self.assertEqual({"wqy_8x16"}, {call[4] for call in canvas.texts})
        self.assertEqual({1, 2}, {call[3] for call in canvas.texts})


if __name__ == "__main__":
    unittest.main()
