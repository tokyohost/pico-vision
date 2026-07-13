#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""为 ESP32 提供按需读取的缝合像素（Fusion Pixel）点阵字体。"""


FONT_HEIGHT = 12
RECORD_SIZE = 17
HEADER_SIZE = 12
FONT_FILE_PATHS = (
    "fonts/fusion_pixel_8px_zh_hans.fpf",
    "/fonts/fusion_pixel_8px_zh_hans.fpf",
)


class FusionPixelFont:
    """使用定长记录和二分索引从闪存读取 Fusion Pixel 字形。"""

    height = FONT_HEIGHT

    def __init__(self, paths=FONT_FILE_PATHS):
        """记录候选字库路径，首次访问字形时才打开文件。"""
        self._paths = paths
        self._source = None
        self._glyph_count = 0
        self._question_mark = None

    def _open(self):
        """打开并校验 FPF 字库文件头。"""
        if self._source is not None:
            return self._source
        last_error = None
        for path in self._paths:
            try:
                source = open(path, "rb")
                header = source.read(HEADER_SIZE)
                if header[:4] != b"FPF1" or header[4] != FONT_HEIGHT:
                    source.close()
                    raise ValueError("Fusion Pixel 字库格式不兼容")
                self._glyph_count = (
                    header[8]
                    | (header[9] << 8)
                    | (header[10] << 16)
                    | (header[11] << 24)
                )
                self._source = source
                return source
            except OSError as error:
                last_error = error
        raise OSError("未找到 Fusion Pixel 字库：{}".format(last_error))

    @staticmethod
    def _codepoint(record):
        """从三字节小端字段解析 Unicode 码点。"""
        return record[0] | (record[1] << 8) | (record[2] << 16)

    def _find_record(self, character):
        """通过二分查找返回指定字符的定长字形记录。"""
        source = self._open()
        target = ord(character)
        left = 0
        right = self._glyph_count - 1
        while left <= right:
            middle = (left + right) // 2
            source.seek(HEADER_SIZE + middle * RECORD_SIZE)
            record = source.read(RECORD_SIZE)
            current = self._codepoint(record)
            if current == target:
                return record
            if current < target:
                left = middle + 1
            else:
                right = middle - 1
        return None

    @staticmethod
    def _columns(record):
        """把逐行位图转换为画布使用的逐列整数位图。"""
        width = record[4]
        rows = record[5:5 + FONT_HEIGHT]
        columns = []
        for column_index in range(width):
            mask = 0x80 >> column_index
            bits = 0
            for row_index, row_bits in enumerate(rows):
                if row_bits & mask:
                    bits |= 1 << row_index
            columns.append(bits)
        return tuple(columns)

    def glyph(self, character):
        """返回字符的逐列位图，缺字时回退为问号字形。"""
        record = self._find_record(character)
        if record is not None:
            return self._columns(record)
        if self._question_mark is None:
            fallback = self._find_record("?")
            self._question_mark = self._columns(fallback) if fallback else (127,)
        return self._question_mark

    def get(self, character, default=None):
        """提供与内置字体字典兼容的字形查询接口。"""
        del default
        return self.glyph(character)

    def __getitem__(self, character):
        """提供与内置字体字典兼容的下标查询接口。"""
        return self.glyph(character)

    def advance(self, character):
        """返回字符在原始比例字体中的水平步进。"""
        record = self._find_record(character)
        if record is None:
            record = self._find_record("?")
        return record[3] if record else 8


FUSION_PIXEL_8PX = FusionPixelFont()
