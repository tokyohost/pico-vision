"""验证 Fusion Pixel 中文字体测试样式。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from styles.style_fusion_pixel_test import FusionPixelTestStyle  # noqa: E402
from styles.style_plugins import create_style  # noqa: E402


class RecordingCanvas:
    """记录字体测试样式发出的文字绘制调用。"""

    def __init__(self):
        """初始化文字调用记录。"""
        self.texts = []

    def clear(self, color):
        """忽略测试无关的背景清理颜色。"""
        del color

    def fill_rect(self, x, y, width, height, color):
        """忽略测试无关的区域背景参数。"""
        del x, y, width, height, color

    def text_width(self, value, scale=1, font_name=None):
        """返回用于居中计算的稳定测试宽度。"""
        del font_name
        return len(str(value)) * 6 * scale

    def text(self, x, y, value, color, scale=1, font_name=None):
        """记录文字内容、位置、缩放和字体名称。"""
        del color
        self.texts.append((x, y, str(value), scale, font_name))


class FusionPixelStyleTest(unittest.TestCase):
    """验证字体测试样式的元数据、条带尺寸和字体选择。"""

    def test_style_metadata_and_registration(self):
        """样式应可按名称创建并沿用 Pico 的紧凑自定义字体。"""
        style = create_style("fusion_pixel_test")

        self.assertEqual("融合像素中文测试", style.zh_name)
        self.assertEqual("screen_2inch_compact", style.font_name)
        self.assertEqual((240, 320), (style.width, style.height))
        self.assertFalse(style.landscape)

    def test_dirty_regions_fit_strip_canvas(self):
        """全部刷新区域都应适配二百四十乘四十的条带画布。"""
        regions = FusionPixelTestStyle.create_dirty_regions()

        self.assertEqual(8, len(regions))
        for _key, _x, _y, width, height in regions:
            self.assertLessEqual(width * height, 240 * 40)

    def test_draw_uses_fusion_font_and_keeps_native_comparison(self):
        """中文测试项应指定 Fusion Pixel，末行应保留紧凑字体对照。"""
        canvas = RecordingCanvas()

        FusionPixelTestStyle.draw_visible(canvas, {})

        calls = {value: font_name for _x, _y, value, _scale, font_name in canvas.texts}
        self.assertEqual("fusion_pixel_8x16", calls["融合像素"])
        self.assertEqual("fusion_pixel_8x16", calls["你好，世界！"])
        self.assertEqual("fusion_pixel_8x16", calls["温度 36℃  帧率 120"])
        self.assertEqual("screen_2inch_compact", calls["COMPACT ABC 123"])


if __name__ == "__main__":
    unittest.main()
