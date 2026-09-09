"""将 Z 工坊大陆字形转换为固件内置十二像素单色点阵。"""

import hashlib
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/fonts/zlabs_pixel_12px/ZLabsPixel_12px_M_CN.ttf"
TARGET = ROOT.parent / "micropython/ports/rp2/modules/fn_canvas"


def build():
    """沿用固件共享字符索引，以原生尺寸生成十二行高位优先位图。"""
    source = (TARGET / "font_builtin_data.c").read_text(encoding="utf-8")
    block = re.search(r"fn_builtin_font_codepoints\[\] = \{(.*?)\n\};", source, re.S)[1]
    index = bytes(int(value, 16) for value in re.findall(r"0x([0-9A-F]{2})", block))
    font = ImageFont.truetype(str(SOURCE), 12)
    bitmap = bytearray()
    for offset in range(0, len(index), 2):
        character = chr(int.from_bytes(index[offset:offset + 2], "little"))
        glyph = Image.new("1", (16, 12))
        # 禁用抗锯齿，保持原始像素网格；顶部锚点沿用字体十像素上升部。
        ImageDraw.Draw(glyph).text((0, 0), character, font=font, fill=1)
        for y in range(12):
            row = sum(int(glyph.getpixel((x, y))) << (15 - x) for x in range(16))
            bitmap.extend(row.to_bytes(2, "big"))
    lines = ["/* Z工坊像素黑体 12px，OFL-1.1，禁止手工编辑，请运行生成脚本。 */",
             "/* 原字体 SHA256: " + hashlib.sha256(SOURCE.read_bytes()).hexdigest() + " */",
             '#include "font_builtin_data.h"',
             "const uint8_t fn_builtin_font_zlabs_bitmap[] = {"]
    lines.extend("    " + ", ".join("0x{:02X}".format(v) for v in bitmap[i:i + 24]) + ","
                 for i in range(0, len(bitmap), 24))
    lines.append("};")
    (TARGET / "font_zlabs_pixel_data.c").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("已生成 {} 个字形，共 {} 字节".format(len(index) // 2, len(bitmap)))


if __name__ == "__main__":
    build()
