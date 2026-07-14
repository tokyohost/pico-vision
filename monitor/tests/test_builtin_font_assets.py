"""验证编译进 MicroPython 固件的双语点阵字体资源。"""

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
FONT_SOURCE = (
    WORKSPACE_ROOT / "micropython" / "ports" / "rp2" / "modules"
    / "fn_canvas" / "font_builtin_data.c"
)


def _supported_characters():
    """返回 SDK 内置字体应覆盖的 ASCII 与 GB2312 字符表。"""
    characters = {chr(codepoint) for codepoint in range(0x20, 0x7F)}
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                characters.add(bytes((lead, trail)).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return tuple(sorted(characters, key=ord))


def _array_bytes(source, name):
    """从生成的 C 数组中解析字节，供资源结构测试使用。"""
    match = re.search(
        r"const uint8_t {}\[\] = \{{(.*?)\n\}};".format(name),
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("未找到字体数组：{}".format(name))
    return bytes(int(value, 16) for value in re.findall(r"0x([0-9A-F]{2})", match.group(1)))


class BuiltinFontAssetsTest(unittest.TestCase):
    """验证字符索引、字形尺寸、字体差异和半角留白。"""

    @classmethod
    def setUpClass(cls):
        """一次读取生成资源，避免每个测试重复解析三兆字节文本。"""
        cls.source = FONT_SOURCE.read_text(encoding="utf-8")
        cls.characters = _supported_characters()
        cls.codepoints = _array_bytes(cls.source, "fn_builtin_font_codepoints")
        cls.wqy = _array_bytes(cls.source, "fn_builtin_font_wqy_bitmap")
        cls.fusion = _array_bytes(cls.source, "fn_builtin_font_fusion_bitmap")

    def _glyph(self, data, character):
        """按排序字符表返回一个三十二字节字形。"""
        index = self.characters.index(character)
        return data[index * 32:(index + 1) * 32]

    def test_shared_index_covers_ascii_and_gb2312(self):
        """共享索引应完整覆盖 ASCII 与可解码的 GB2312 字符。"""
        self.assertEqual(7540, len(self.characters))
        decoded = tuple(
            self.codepoints[index] | (self.codepoints[index + 1] << 8)
            for index in range(0, len(self.codepoints), 2)
        )
        self.assertEqual(tuple(map(ord, self.characters)), decoded)
        self.assertIn("中", self.characters)
        self.assertIn("℃", self.characters)

    def test_each_font_contains_one_16px_glyph_per_character(self):
        """每套字体都应为每个字符保存十六乘十六单色字形。"""
        expected_size = len(self.characters) * 32
        self.assertEqual(expected_size, len(self.wqy))
        self.assertEqual(expected_size, len(self.fusion))
        self.assertTrue(any(self._glyph(self.wqy, "中")))
        self.assertTrue(any(self._glyph(self.fusion, "中")))

    def test_fonts_are_distinct_and_ascii_uses_left_half(self):
        """两套中文外观应不同，ASCII 右侧八列必须保持空白。"""
        self.assertNotEqual(self._glyph(self.wqy, "中"), self._glyph(self.fusion, "中"))
        for data in (self.wqy, self.fusion):
            glyph = self._glyph(data, "A")
            for row in range(16):
                self.assertEqual(0, glyph[row * 2 + 1])


if __name__ == "__main__":
    unittest.main()
