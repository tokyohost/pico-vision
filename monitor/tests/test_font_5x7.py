"""验证两套设备固件的 5×7 字体保留小写 g 的完整降部。"""

import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FontDescenderTest(unittest.TestCase):
    """按实际列位序检查基础字体及两个派生字体的字形。"""

    def test_g_bitmap_preserves_descender_in_all_fonts(self):
        """两套固件的三种字体都应绘制完整字腹和第六行降部。"""
        expected_rows = (
            ".....",
            ".....",
            ".###.",
            "#...#",
            "#...#",
            ".####",
            "...#.",
        )
        for board in ("esp32-s3", "picoRP2040"):
            font_root = PROJECT_ROOT / board
            native = runpy.run_path(str(font_root / "font_5x7.py"))
            # 隔离同名模块，让派生字体始终继承当前受测固件的数据。
            font_module = types.ModuleType("font_5x7")
            font_module.FONT_5X7 = native["FONT_5X7"]
            with mock.patch.dict(sys.modules, {"font_5x7": font_module}):
                derived = runpy.run_path(str(font_root / "font_screen_2inch.py"))
            fonts = {
                "native": native["FONT_5X7"],
                "screen_2inch": derived["FONT_SCREEN_2INCH"],
                "screen_2inch_compact": derived["FONT_SCREEN_2INCH_COMPACT"],
            }
            for name, font in fonts.items():
                with self.subTest(board=board, font=name):
                    columns = font["g"]
                    self.assertEqual(5, len(columns))
                    self.assertTrue(all(0 <= bits < 128 for bits in columns))
                    rows = tuple(
                        "".join("#" if bits & (1 << row) else "." for bits in columns)
                        for row in range(7)
                    )
                    self.assertEqual(expected_rows, rows)


if __name__ == "__main__":
    unittest.main()
