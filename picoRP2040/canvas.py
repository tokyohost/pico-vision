"""提供带纵向裁剪的 RGB565 条带绘图能力。"""

from config import BLACK
from font_5x7 import FONT_5X7
from font_screen_2inch import FONT_SCREEN_2INCH, FONT_SCREEN_2INCH_COMPACT

try:
    import framebuf
except ImportError:
    framebuf = None


class Canvas:
    """在小型条带缓冲区中绘图，坐标仍使用完整屏幕坐标。"""

    def __init__(self, width, height):
        """创建指定大小的 RGB565 条带缓冲区。"""
        self.width = width
        self.height = height
        self.origin_x = 0
        self.origin_y = 0
        self.buffer = bytearray(width * height * 2)
        self._capacity_pixels = width * height
        self._framebuffers = {}
        self._framebuffer = None
        self._glyph_cache = {}
        self._font_name = "native"
        self._font = FONT_5X7
        self._select_framebuffer()

    def set_font(self, font_name):
        """选择当前样式使用的点阵字体。"""
        normalized_name = str(font_name or "native").strip().lower()
        fonts = {
            "native": FONT_5X7,
            "screen_2inch": FONT_SCREEN_2INCH,
            "screen_2inch_compact": FONT_SCREEN_2INCH_COMPACT,
        }
        if normalized_name not in fonts:
            raise ValueError("未知点阵字体：{}".format(normalized_name))
        self._font_name = normalized_name
        self._font = fonts[normalized_name]

    def set_origin(self, origin_y):
        """设置当前条带在完整屏幕中的纵向起点。"""
        self.origin_x = 0
        self.origin_y = origin_y
        self._select_framebuffer()

    def set_view(self, origin_x, origin_y, width, height):
        """设置可变尺寸脏矩形视口并复用现有缓冲区。"""
        if width * height > self._capacity_pixels:
            raise ValueError("脏矩形超过画布容量")
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.width = width
        self.height = height
        self._select_framebuffer()

    def _select_framebuffer(self):
        """选择或创建当前视口对应的原生 FrameBuffer。"""
        if framebuf is None:
            self._framebuffer = None
            return
        key = (self.width, self.height)
        current = self._framebuffers.get(key)
        if current is None:
            current = framebuf.FrameBuffer(
                self.buffer,
                self.width,
                self.height,
                framebuf.RGB565,
            )
            self._framebuffers[key] = current
        self._framebuffer = current

    @staticmethod
    def _native_color(color):
        """将大端 RGB565 转换为 FrameBuffer 使用的本机字节序。"""
        return ((color & 0xFF) << 8) | ((color >> 8) & 0xFF)

    @staticmethod
    def _pixel_bytes(color):
        """将 RGB565 整数转换为大端双字节像素。"""
        return bytes(((color >> 8) & 0xFF, color & 0xFF))

    def clear(self, color=BLACK):
        """使用指定颜色清空当前条带。"""
        if self._framebuffer is not None:
            self._framebuffer.fill(self._native_color(color))
            return
        row = self._pixel_bytes(color) * self.width
        for local_y in range(self.height):
            start = local_y * len(row)
            self.buffer[start:start + len(row)] = row

    def pixel(self, x, y, color):
        """在当前条带范围内绘制一个像素。"""
        local_x = x - self.origin_x
        local_y = y - self.origin_y
        if 0 <= local_x < self.width and 0 <= local_y < self.height:
            if self._framebuffer is not None:
                self._framebuffer.pixel(
                    local_x,
                    local_y,
                    self._native_color(color),
                )
                return
            offset = (local_y * self.width + local_x) * 2
            self.buffer[offset] = (color >> 8) & 0xFF
            self.buffer[offset + 1] = color & 0xFF

    def fill_rect(self, x, y, width, height, color):
        """绘制经过当前条带边界裁剪的实心矩形。"""
        left = max(self.origin_x, x)
        top = max(self.origin_y, y)
        right = min(self.origin_x + self.width, x + width)
        bottom = min(self.origin_y + self.height, y + height)
        if left >= right or top >= bottom:
            return
        if self._framebuffer is not None:
            self._framebuffer.fill_rect(
                left - self.origin_x,
                top - self.origin_y,
                right - left,
                bottom - top,
                self._native_color(color),
            )
            return
        row = self._pixel_bytes(color) * (right - left)
        for line_y in range(top, bottom):
            start = (
                (line_y - self.origin_y) * self.width
                + left - self.origin_x
            ) * 2
            self.buffer[start:start + len(row)] = row

    def line(self, x0, y0, x1, y1, color):
        """使用整数 Bresenham 算法绘制线段。"""
        if self._framebuffer is not None:
            self._framebuffer.line(
                x0 - self.origin_x,
                y0 - self.origin_y,
                x1 - self.origin_x,
                y1 - self.origin_y,
                self._native_color(color),
            )
            return
        delta_x = abs(x1 - x0)
        step_x = 1 if x0 < x1 else -1
        delta_y = -abs(y1 - y0)
        step_y = 1 if y0 < y1 else -1
        error = delta_x + delta_y
        while True:
            self.pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            doubled = error * 2
            if doubled >= delta_y:
                error += delta_y
                x0 += step_x
            if doubled <= delta_x:
                error += delta_x
                y0 += step_y

    def text(self, x, y, value, color, scale=1):
        """使用内置点阵字体绘制文本，并按实际字形宽度推进光标。"""
        value = str(value)
        if (
            self._framebuffer is not None
            and scale == 1
            and self._font_name == "native"
            and all(ord(character) < 128 for character in value)
        ):
            self._framebuffer.text(
                value,
                x - self.origin_x,
                y - self.origin_y,
                self._native_color(color),
            )
            return
        if self._framebuffer is not None and scale == 1:
            self._blit_font_text(x, y, value, color)
            return
        if self._framebuffer is not None and scale > 1:
            self._blit_scaled_text(x, y, value, color, scale)
            return
        cursor_x = x
        for character in value:
            columns = self._font.get(character, self._font["?"])
            for column_index, bits in enumerate(columns):
                for row_index in range(7):
                    if bits & (1 << row_index):
                        self.fill_rect(
                            cursor_x + column_index * scale,
                            y + row_index * scale,
                            scale, scale, color,
                        )
            cursor_x += self._character_advance(character, scale)

    def text_width(self, value, scale=1):
        """根据当前字体的实际字形宽度计算文本占用像素宽度。"""
        return sum(self._character_advance(character, scale) for character in str(value))

    def _character_advance(self, character, scale=1):
        """返回单个字符的水平步进，宽字形会自动扩展间距。"""
        columns = self._font.get(character, self._font["?"])
        if self._font_name == "screen_2inch_compact":
            return (len(columns) + 1) * scale
        if scale == 1 and self._font_name != "native":
            return max(8, len(columns) + 1)
        return max(6, len(columns) + 1) * scale

    def _blit_font_text(self, x, y, value, color):
        """按照原生字符间距绘制当前样式选择的点阵字体。"""
        cursor_x = x
        transparent = self._native_color(BLACK)
        for character in value:
            glyph = self._get_scaled_glyph(character, color, 1)
            offset = 1 if self._font_name == "screen_2inch" else 0
            self._framebuffer.blit(
                glyph,
                cursor_x + offset - self.origin_x,
                y - self.origin_y,
                transparent,
            )
            cursor_x += self._character_advance(character, 1)

    def _blit_scaled_text(self, x, y, value, color, scale):
        """使用缓存字形快速绘制放大文本。"""
        cursor_x = x
        transparent = self._native_color(BLACK)
        for character in value:
            glyph = self._get_scaled_glyph(character, color, scale)
            self._framebuffer.blit(
                glyph,
                cursor_x - self.origin_x,
                y - self.origin_y,
                transparent,
            )
            cursor_x += self._character_advance(character, scale)

    def _get_scaled_glyph(self, character, color, scale):
        """获取或创建指定字符的原生放大字形缓存。"""
        key = (self._font_name, character, color, scale)
        glyph = self._glyph_cache.get(key)
        if glyph is not None:
            return glyph
        columns = self._font.get(character, self._font["?"])
        width = max(6, len(columns)) * scale
        height = 7 * scale
        glyph_buffer = bytearray(width * height * 2)
        glyph = framebuf.FrameBuffer(
            glyph_buffer,
            width,
            height,
            framebuf.RGB565,
        )
        glyph.fill(self._native_color(BLACK))
        native_color = self._native_color(color)
        for column_index, bits in enumerate(columns):
            for row_index in range(7):
                if bits & (1 << row_index):
                    glyph.fill_rect(
                        column_index * scale,
                        row_index * scale,
                        scale,
                        scale,
                        native_color,
                    )
        self._glyph_cache[key] = glyph
        return glyph
