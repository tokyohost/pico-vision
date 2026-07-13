"""把 Fusion Pixel BDF 字体转换为 ESP32 可按需读取的 FPF 字库。"""


import argparse
import struct
from pathlib import Path


FONT_HEIGHT = 12
FONT_ASCENT = 9
RECORD_SIZE = 17


def _parse_glyph(lines):
    """解析一段 BDF 字形并返回 FPF 定长记录。"""
    encoding = None
    advance = 8
    bounding_box = (0, 0, 0, 0)
    bitmap = []
    reading_bitmap = False
    for line in lines:
        if line.startswith("ENCODING "):
            encoding = int(line.split()[1])
        elif line.startswith("DWIDTH "):
            advance = int(line.split()[1])
        elif line.startswith("BBX "):
            bounding_box = tuple(int(value) for value in line.split()[1:5])
        elif line == "BITMAP":
            reading_bitmap = True
        elif reading_bitmap:
            bitmap.append(int(line, 16))
    if encoding is None or not 0 <= encoding <= 0x10FFFF:
        return None
    width, height, offset_x, offset_y = bounding_box
    rows = bytearray(FONT_HEIGHT)
    top = FONT_ASCENT - (offset_y + height)
    for source_y, row_bits in enumerate(bitmap):
        target_y = top + source_y
        if 0 <= target_y < FONT_HEIGHT:
            if offset_x >= 0:
                rows[target_y] = (row_bits >> offset_x) & 0xFF
            else:
                rows[target_y] = (row_bits << -offset_x) & 0xFF
    codepoint = bytes((encoding & 0xFF, (encoding >> 8) & 0xFF, (encoding >> 16) & 0xFF))
    return codepoint + bytes((advance, min(8, max(0, width + max(0, offset_x))))) + rows


def convert_bdf(source_path, target_path):
    """转换完整 BDF 文件，并按 Unicode 码点排序写入目标字库。"""
    records = []
    glyph_lines = None
    with source_path.open("r", encoding="ascii") as source:
        for raw_line in source:
            line = raw_line.rstrip("\r\n")
            if line.startswith("STARTCHAR "):
                glyph_lines = []
            elif line == "ENDCHAR" and glyph_lines is not None:
                record = _parse_glyph(glyph_lines)
                if record is not None:
                    records.append(record)
                glyph_lines = None
            elif glyph_lines is not None:
                glyph_lines.append(line)
    records.sort(key=lambda record: record[0] | (record[1] << 8) | (record[2] << 16))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as target:
        target.write(b"FPF1")
        target.write(bytes((FONT_HEIGHT, RECORD_SIZE, 0, 0)))
        target.write(struct.pack("<I", len(records)))
        target.writelines(records)
    return len(records)


def main():
    """解析命令行参数并执行字体转换。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Fusion Pixel 简体中文 BDF 文件")
    parser.add_argument("target", type=Path, help="输出 FPF 字库文件")
    args = parser.parse_args()
    count = convert_bdf(args.source, args.target)
    print("已写入 {} 个字形：{}".format(count, args.target))


if __name__ == "__main__":
    main()
