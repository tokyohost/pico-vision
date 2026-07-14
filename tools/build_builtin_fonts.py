"""生成供 MicroPython ``fn_canvas`` 直接链接的双语点阵字体数据。"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_HEIGHT = 16
ASCII_ADVANCE = 8
FPF_HEADER_SIZE = 12
FPF_RECORD_SIZE = 17
FPF_SOURCE_HEIGHT = 12


def _supported_characters():
    """返回 ASCII 与 GB2312 字符组成的稳定 Unicode 字符表。"""
    characters = {chr(codepoint) for codepoint in range(0x20, 0x7F)}
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                characters.add(bytes((lead, trail)).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return tuple(sorted(characters, key=ord))


def _pack_image(image):
    """把十六乘十六单色图像按逐行高位优先格式打包。"""
    packed = bytearray()
    for y in range(FONT_HEIGHT):
        row = 0
        for x in range(FONT_HEIGHT):
            if image.getpixel((x, y)):
                row |= 1 << (FONT_HEIGHT - 1 - x)
        packed.extend(((row >> 8) & 0xFF, row & 0xFF))
    return bytes(packed)


def _render_wqy_glyph(font, character):
    """从文泉驿点阵正黑的十六像素内嵌位图渲染一个字形。"""
    natural_width = ASCII_ADVANCE + 1 if ord(character) < 0x80 else FONT_HEIGHT
    source = Image.new("1", (natural_width, FONT_HEIGHT), 0)
    ImageDraw.Draw(source).text((0, -2), character, font=font, fill=1)
    if ord(character) < 0x80 and source.getbbox() is not None:
        source = source.resize((ASCII_ADVANCE, FONT_HEIGHT), Image.Resampling.NEAREST)
    target = Image.new("1", (FONT_HEIGHT, FONT_HEIGHT), 0)
    target.paste(source, (0, 0))
    return _pack_image(target)


def _load_fpf(path):
    """读取并校验旧版 Fusion Pixel FPF 字库记录。"""
    data = path.read_bytes()
    if data[:4] != b"FPF1" or data[4] != FPF_SOURCE_HEIGHT:
        raise ValueError("Fusion Pixel FPF 字库格式不兼容")
    record_size = data[5]
    if record_size != FPF_RECORD_SIZE:
        raise ValueError("Fusion Pixel FPF 记录长度不兼容")
    count = int.from_bytes(data[8:12], "little")
    records = {}
    for index in range(count):
        start = FPF_HEADER_SIZE + index * record_size
        record = data[start:start + record_size]
        codepoint = int.from_bytes(record[:3], "little")
        records[codepoint] = record
    return records


def _render_fusion_glyph(records, character):
    """把 Fusion Pixel 8px 字形整数放大到半角八、全角十六像素。"""
    record = records.get(ord(character)) or records[ord("?")]
    width = record[4]
    rows = record[5:5 + FPF_SOURCE_HEIGHT]
    source_rows = rows[2:10]
    image = Image.new("1", (FONT_HEIGHT, FONT_HEIGHT), 0)
    full_width = ord(character) >= 0x80
    horizontal_scale = 2 if full_width else 1
    for source_y, row_bits in enumerate(source_rows):
        for source_x in range(width):
            if row_bits & (0x80 >> source_x):
                for offset_y in range(2):
                    for offset_x in range(horizontal_scale):
                        image.putpixel((
                            source_x * horizontal_scale + offset_x,
                            source_y * 2 + offset_y,
                        ), 1)
    return _pack_image(image)


def _format_array(name, data, columns=16):
    """把字节数据格式化为带中文说明的 C 只读数组。"""
    lines = ["/** {}。 */".format(name), "const uint8_t {}[] = {{".format(name)]
    for offset in range(0, len(data), columns):
        chunk = data[offset:offset + columns]
        lines.append("    " + ", ".join("0x{:02X}".format(value) for value in chunk) + ",")
    lines.append("};")
    return "\n".join(lines)


def build_fonts(wqy_path, fusion_path, output_path):
    """生成两套共享字符索引的固件 C 字体资源。"""
    characters = _supported_characters()
    wqy_font = ImageFont.truetype(str(wqy_path), FONT_HEIGHT, index=2)
    if wqy_font.getname()[0] != "WenQuanYi Zen Hei Sharp":
        raise ValueError("输入文件不包含文泉驿点阵正黑字体面")
    fusion_records = _load_fpf(fusion_path)
    codepoints = bytearray()
    wqy_data = bytearray()
    fusion_data = bytearray()
    for character in characters:
        codepoints.extend((ord(character) & 0xFF, ord(character) >> 8))
        wqy_data.extend(_render_wqy_glyph(wqy_font, character))
        fusion_data.extend(_render_fusion_glyph(fusion_records, character))
    content = "\n\n".join((
        "/* 本文件由 pico-project/tools/build_builtin_fonts.py 自动生成，请勿手工修改。 */\n"
        "#include <stdint.h>\n\n"
        "#include \"font_builtin_data.h\"\n\n"
        "const uint32_t fn_builtin_font_glyph_count = {}U;".format(len(characters)),
        _format_array("fn_builtin_font_codepoints", codepoints),
        _format_array("fn_builtin_font_wqy_bitmap", wqy_data),
        _format_array("fn_builtin_font_fusion_bitmap", fusion_data),
        "",
    ))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8", newline="\n")
    return len(characters)


def main():
    """解析生成参数并输出固件字体数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wqy", required=True, type=Path, help="文泉驿 wqy-zenhei.ttc 路径")
    parser.add_argument("--fusion", required=True, type=Path, help="Fusion Pixel FPF 路径")
    parser.add_argument("--output", required=True, type=Path, help="输出 font_builtin_data.c 路径")
    arguments = parser.parse_args()
    count = build_fonts(arguments.wqy, arguments.fusion, arguments.output)
    print("已生成 {} 个字符的两套固件字形：{}".format(count, arguments.output))


if __name__ == "__main__":
    main()
