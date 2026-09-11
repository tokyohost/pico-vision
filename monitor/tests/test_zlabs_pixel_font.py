"""验证 Z 工坊字体资源、固件兼容提示及测试样式。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_builtin_font_assets import _array_bytes, _supported_characters
from test_fusion_pixel_style import RecordingCanvas

ROOT = Path(__file__).resolve().parents[2]
ZLABS_BITMAP_SOURCE = (
    ROOT.parent / "micropython" / "ports" / "rp2" / "modules"
    / "fn_canvas" / "font_zlabs_pixel_data.c"
)
sys.path.insert(0, str(ROOT / "picoRP2040"))
import canvas
import canvasC
import font_builtin
from styles.style_plugins import create_style


class ZLabsPixelFontTest(unittest.TestCase):
    """检查十二像素资源和两条画布渲染路径的接入行为。"""

    @unittest.skipUnless(
        ZLABS_BITMAP_SOURCE.is_file(),
        "当前检出内容不包含 MicroPython 的 Z 工坊字体点阵资源",
    )
    def test_bitmap_matches_original_font(self):
        """点阵应保持原字体像素，不发生缩放或基线裁剪。"""
        from PIL import Image, ImageDraw, ImageFont
        data = _array_bytes(
            ZLABS_BITMAP_SOURCE.read_text(encoding="utf-8"),
            "fn_builtin_font_zlabs_bitmap",
        )
        characters = _supported_characters()
        self.assertEqual(len(characters) * 24, len(data))
        font = ImageFont.truetype(str(ROOT / "assets/fonts/zlabs_pixel_12px/ZLabsPixel_12px_M_CN.ttf"), 12)
        for character in "Ag中你好，世界！℃【】":
            index = characters.index(character)
            glyph = data[index * 24:(index + 1) * 24]
            original = Image.new("1", (16, 12))
            ImageDraw.Draw(original).text((0, 0), character, font=font, fill=1)
            self.assertTrue(any(glyph))
            for y in range(12):
                row = int.from_bytes(glyph[y * 2:y * 2 + 2], "big")
                for x in range(16):
                    self.assertEqual(bool(original.getpixel((x, y))), bool(row & (0x8000 >> x)))

    def test_python_font_height_and_old_firmware_error(self):
        """Python 画布应识别十二像素高度并明确拒绝旧固件。"""
        drawing = canvas.Canvas(240, 40)
        drawing.set_font("zlabs_pixel_12px")
        self.assertEqual(12, drawing._font_height())
        with patch.object(font_builtin, "_native_canvas", Mock(api_version=lambda: 9)):
            with self.assertRaisesRegex(RuntimeError, "API 10"):
                drawing.text_width("中文")

    def test_native_font_forwarding_and_state_restore(self):
        """C 画布应使用编号五，并在成功或异常后恢复默认字体。"""
        native = Mock(api_version=lambda: 10)
        native.text_width.return_value = 18
        with patch.object(canvasC, "_native_canvas", native):
            drawing = canvasC.CanvasC(240, 40)
            self.assertEqual(18, drawing.text_width("中A", font_name="zlabs_pixel_12px"))
            native.text_width.assert_called_once_with(5, "中A", 1)
            drawing.text(1, 2, "中A", 0xFFFF, font_name="zlabs_pixel_12px")
            self.assertEqual(5, native.draw_text.call_args.args[6])
            self.assertEqual("native", drawing._font_name)
            native.api_version = lambda: 9
            with self.assertRaisesRegex(RuntimeError, "API 10"):
                drawing.text(1, 2, "中文", 0xFFFF, font_name="zlabs_pixel_12px")
            self.assertEqual("native", drawing._font_name)

    def test_style_registration_and_strip_layout(self):
        """测试页应可动态加载，覆盖全屏且所有文本位于屏幕范围内。"""
        style = create_style("zlabs_pixel_test")
        self.assertEqual("Z工坊12px字体测试", style.zh_name)
        self.assertEqual(8, len(style.create_dirty_regions()))
        for _key, x, y, width, height in style.create_dirty_regions():
            self.assertEqual((0, 240, 40), (x, width, height))
            self.assertLessEqual(y + height, 320)
        drawing = RecordingCanvas()
        style.draw_visible(drawing, {})
        for x, y, value, scale, font_name in drawing.texts:
            height = 12 if font_name == "zlabs_pixel_12px" else 7
            width = sum(6 if ord(c) < 128 else 12 for c in value) * scale
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + width, 240)
            self.assertLessEqual(y + height * scale, 320)


if __name__ == "__main__":
    unittest.main()
