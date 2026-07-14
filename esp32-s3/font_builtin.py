"""提供对 ``fn_canvas`` 固件内置双语点阵字体的轻量访问。"""

try:
    import fn_canvas as _native_canvas
except ImportError:
    _native_canvas = None


class BuiltinFont:
    """把固件字形查询接口适配为 Canvas 使用的字体对象。"""

    height = 16

    def __init__(self, name, kind):
        """保存公开字体名称和固件字体编号。"""
        self.name = name
        self.kind = kind

    @staticmethod
    def _require_native_canvas():
        """返回固件模块，不支持内置字体时抛出明确错误。"""
        if _native_canvas is None or not hasattr(_native_canvas, "font_glyph"):
            raise RuntimeError("当前 MicroPython 固件未编译 fn_canvas 双语字体")
        return _native_canvas

    def glyph(self, character):
        """从固件只读区读取字符的逐列位图。"""
        return self._require_native_canvas().font_glyph(self.kind, character)

    def get(self, character, default=None):
        """提供与字典字体一致的字形查询接口。"""
        del default
        return self.glyph(character)

    def __getitem__(self, character):
        """提供与字典字体一致的下标访问接口。"""
        return self.glyph(character)

    def advance(self, character):
        """返回半角八像素或全角十六像素的水平步进。"""
        return self._require_native_canvas().text_width(self.kind, character, 1)


WQY_8X16 = BuiltinFont("wqy_8x16", 3)
FUSION_PIXEL_8X16 = BuiltinFont("fusion_pixel_8x16", 4)
