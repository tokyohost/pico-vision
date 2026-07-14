"""验证 Canvas C 加速适配器的能力检测与参数转发。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
sys.path.insert(0, str(PICO_ROOT))

import canvasC  # noqa: E402
from font_builtin import FUSION_PIXEL_8X16  # noqa: E402


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
        self.canvas._font_name = "screen_2inch_compact"
        self.canvas._font = object()

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

    def test_text_temporarily_uses_compiled_font_and_restores_style_font(self):
        """单次文字应使用固件字体编号并在绘制后恢复样式默认字体。"""
        previous_font = self.canvas._font
        native_module = mock.Mock()
        native_module.api_version.return_value = 8
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            self.canvas.text(
                3,
                4,
                "中文",
                0xFFFF,
                font_name="fusion_pixel_8x16",
            )

        native_module.draw_text.assert_called_once_with(
            self.canvas.buffer,
            8,
            6,
            2,
            3,
            FUSION_PIXEL_8X16,
            4,
            3,
            4,
            "中文",
            0xFFFF,
            1,
        )
        self.assertEqual("screen_2inch_compact", self.canvas._font_name)
        self.assertIs(previous_font, self.canvas._font)

    def test_text_width_temporarily_uses_compiled_font(self):
        """指定固件字体的宽度计算应调用同一字体编号并恢复样式字体。"""
        previous_font = self.canvas._font
        native_module = mock.Mock()
        native_module.api_version.return_value = 8
        native_module.text_width.return_value = 48
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            width = self.canvas.text_width(
                "中文A",
                font_name="fusion_pixel_8x16",
            )

        self.assertEqual(48, width)
        native_module.text_width.assert_called_once_with(4, "中文A", 1)
        self.assertEqual("screen_2inch_compact", self.canvas._font_name)
        self.assertIs(previous_font, self.canvas._font)

    def test_api_seven_keeps_basic_native_acceleration(self):
        """未带大字体的 API 7 固件应继续使用基础 Canvas C 加速。"""
        native_module = mock.Mock()
        native_module.api_version.return_value = 7
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            self.assertTrue(canvasC.native_canvas_supported())
            self.assertFalse(canvasC.builtin_fonts_supported())

    def test_api_seven_rejects_builtin_font_with_clear_message(self):
        """API 7 固件选择内置大字体时应返回明确错误。"""
        native_module = mock.Mock()
        native_module.api_version.return_value = 7
        with mock.patch.object(canvasC, "_native_canvas", native_module):
            with self.assertRaisesRegex(RuntimeError, "未编译固件内置字体"):
                self.canvas.text_width("中文", font_name="wqy_8x16")


if __name__ == "__main__":
    unittest.main()
