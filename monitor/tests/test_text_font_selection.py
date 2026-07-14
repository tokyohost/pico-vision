"""验证画布文字可以按单次调用选择字体。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

import canvas as canvas_module  # noqa: E402
import font_fusion_pixel as fusion_font_module  # noqa: E402


class StubFusionFont:
    """提供不访问字库文件的 Fusion Pixel 测试字形。"""

    height = 9

    def glyph(self, character):
        """返回带第九行像素的固定测试字形。"""
        del character
        return (1 << 8,)

    def advance(self, character):
        """返回便于断言的固定比例字体步进。"""
        del character
        return 4


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

    def test_text_can_temporarily_use_fusion_pixel_font(self):
        """单次文字可选择 Fusion Pixel 且调用后恢复默认字体。"""
        drawing_canvas = canvas_module.Canvas(20, 20)
        stub_font = StubFusionFont()
        with mock.patch.object(
            fusion_font_module,
            "FUSION_PIXEL_8PX",
            stub_font,
        ):
            drawing_canvas.text(
                0,
                0,
                "中",
                0xFFFF,
                font_name="fusion_pixel_8px",
            )

        self.assertEqual("native", drawing_canvas._font_name)
        pixel_offset = (8 * drawing_canvas.width) * 2
        self.assertEqual(0xFF, drawing_canvas.buffer[pixel_offset])
        self.assertEqual(0xFF, drawing_canvas.buffer[pixel_offset + 1])

    def test_text_width_can_use_same_temporary_font(self):
        """指定字体的宽度计算应与文字绘制使用相同字体且不改变默认值。"""
        drawing_canvas = canvas_module.Canvas(20, 20)
        drawing_canvas.set_font("screen_2inch_compact")
        stub_font = StubFusionFont()
        with mock.patch.object(
            fusion_font_module,
            "FUSION_PIXEL_8PX",
            stub_font,
        ):
            width = drawing_canvas.text_width(
                "中文",
                font_name="fusion_pixel_8px",
            )

        self.assertEqual(8, width)
        self.assertEqual("screen_2inch_compact", drawing_canvas._font_name)


if __name__ == "__main__":
    unittest.main()
