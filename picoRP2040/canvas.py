#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""提供带纵向裁剪的 RGB565 条带绘图能力。"""


from array import array

from config import BLACK
from font_5x7 import FONT_5X7
from font_screen_2inch import FONT_SCREEN_2INCH, FONT_SCREEN_2INCH_COMPACT

try:
    import framebuf
except ImportError:
    framebuf = None


# RP2040 堆空间有限，但横屏仪表盘会同时使用多种颜色的字母与数字。
# 过小的缓存会在一帧内反复清空并重建字形，128 项可在较低内存开销下
# 容纳常用字形组合。
MAX_GLYPH_CACHE_SIZE = 128
MAX_TEXT_CACHE_BYTES = 2 * 1024
MAX_TEXT_BITMAP_BYTES = 256
MAX_TEXT_SEEN_KEYS = 64
MAX_POLYGON_BUFFER_SHAPES = 8

DRAW_COMMAND_FILL_RECT = 0
DRAW_COMMAND_LINE = 1
DRAW_COMMAND_RECT = 2


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
        self._palette_cache = {}
        self._text_cache = {}
        self._text_cache_bytes = 0
        self._text_seen = {}
        self._font_name = "native"
        self._font = FONT_5X7
        self._polygon_supported = None
        self._polygon_buffers = {}
        self._select_framebuffer()

    @staticmethod
    def _font_definition(font_name):
        """解析字体名称并返回规范名称及对应字形数据。"""
        normalized_name = str(font_name or "native").strip().lower()
        fonts = {
            "native": FONT_5X7,
            "screen_2inch": FONT_SCREEN_2INCH,
            "screen_2inch_compact": FONT_SCREEN_2INCH_COMPACT,
        }
        if normalized_name in ("wqy_8x16", "fusion_pixel_8x16"):
            from font_builtin import FUSION_PIXEL_8X16, WQY_8X16
            fonts.update({
                "wqy_8x16": WQY_8X16,
                "fusion_pixel_8x16": FUSION_PIXEL_8X16,
            })
        if normalized_name not in fonts:
            raise ValueError("未知点阵字体：{}".format(normalized_name))
        return normalized_name, fonts[normalized_name]

    def set_font(self, font_name):
        """选择未单独指定字体时使用的画布默认点阵字体。"""
        normalized_name, font = self._font_definition(font_name)
        if normalized_name != self._font_name:
            self.clear_glyph_cache()
        self._font_name = normalized_name
        self._font = font

    def _select_text_font(self, font_name):
        """临时选择本次文字调用的字体并返回原字体状态。"""
        if font_name is None:
            return None
        previous = (self._font_name, self._font)
        self._font_name, self._font = self._font_definition(font_name)
        return previous

    def _restore_text_font(self, previous):
        """恢复单次文字调用之前的画布字体状态。"""
        if previous is not None:
            self._font_name, self._font = previous

    def clear_glyph_cache(self):
        """清空动态字形缓存，释放样式切换遗留的帧缓冲区。"""
        self._glyph_cache.clear()
        self._palette_cache.clear()
        self._text_cache.clear()
        self._text_cache_bytes = 0
        self._text_seen.clear()
        self._polygon_buffers.clear()

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

    def fill_round_rect(self, x, y, width, height, color, radius=3):
        """Fill a small rounded rectangle without changing panel outlines."""
        if width <= 0 or height <= 0:
            return
        radius = min(radius, width // 2, height // 2)
        if radius <= 1:
            self.fill_rect(x, y, width, height, color)
            return
        for row in range(radius):
            inset = (radius - row + 1) // 2
            self.fill_rect(
                x + inset, y + row, width - inset * 2, 1, color
            )
            self.fill_rect(
                x + inset, y + height - row - 1,
                width - inset * 2, 1, color,
            )
        middle_height = height - radius * 2
        if middle_height > 0:
            self.fill_rect(x, y + radius, width, middle_height, color)

    def line(self, x0, y0, x1, y1, color):
        """使用整数 Bresenham 算法绘制线段。"""
        if self._framebuffer is not None:
            native_color = self._native_color(color)
            if y0 == y1:
                self._framebuffer.hline(
                    min(x0, x1) - self.origin_x,
                    y0 - self.origin_y,
                    abs(x1 - x0) + 1,
                    native_color,
                )
                return
            if x0 == x1:
                self._framebuffer.vline(
                    x0 - self.origin_x,
                    min(y0, y1) - self.origin_y,
                    abs(y1 - y0) + 1,
                    native_color,
                )
                return
            self._framebuffer.line(
                x0 - self.origin_x,
                y0 - self.origin_y,
                x1 - self.origin_x,
                y1 - self.origin_y,
                native_color,
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

    def draw_commands(self, commands):
        """依次执行通用批量绘图命令，并为 Python 后端保持相同接口。"""
        for operation, x, y, value_a, value_b, color in commands:
            if operation == DRAW_COMMAND_FILL_RECT:
                self.fill_rect(x, y, value_a, value_b, color)
            elif operation == DRAW_COMMAND_LINE:
                self.line(x, y, value_a, value_b, color)
            elif operation == DRAW_COMMAND_RECT:
                self.line(x, y, x + value_a - 1, y, color)
                self.line(x, y + value_b - 1,
                          x + value_a - 1, y + value_b - 1, color)
                self.line(x, y, x, y + value_b - 1, color)
                self.line(x + value_a - 1, y,
                          x + value_a - 1, y + value_b - 1, color)
            else:
                raise ValueError("未知批量绘图命令：{}".format(operation))

    def fill_polygon(self, points, color):
        """优先调用原生 FrameBuffer 一次性填充多边形，并返回是否成功。"""
        if len(points) >= 2:
            baseline_y = points[0][1]
            if all(point[1] == baseline_y for point in points[1:]):
                # 全零面积图会退化为水平线，显式绘制以免原生填充静默丢失。
                left = min(point[0] for point in points)
                right = max(point[0] for point in points)
                self.line(left, baseline_y, right, baseline_y, color)
                return True
        if self._polygon_supported is False or self._framebuffer is None:
            return False
        polygon_method = getattr(self._framebuffer, "poly", None)
        if polygon_method is None:
            self._polygon_supported = False
            return False
        try:
            coordinate_count = len(points) * 2
            coordinates = self._polygon_buffers.get(coordinate_count)
            if coordinates is None:
                coordinates = array("h", [0] * coordinate_count)
                if len(self._polygon_buffers) < MAX_POLYGON_BUFFER_SHAPES:
                    self._polygon_buffers[coordinate_count] = coordinates
            coordinate_index = 0
            for point_x, point_y in points:
                coordinates[coordinate_index] = point_x
                coordinates[coordinate_index + 1] = point_y
                coordinate_index += 2
            polygon_method(
                -self.origin_x, -self.origin_y, coordinates,
                self._native_color(color), True,
            )
            self._polygon_supported = True
            return True
        except (
            AttributeError, MemoryError, OSError,
            OverflowError, RuntimeError, TypeError, ValueError,
        ):
            # 不同 MicroPython 固件的 poly 签名并不一致，失败后使用扫描线。
            self._polygon_supported = False
            return False

    def draw_columns(self, columns, bottom=None):
        """Draw sampled columns, grouping equal colors into native polygons.

        ``columns`` contains ``(x, y, color)`` tuples.  With ``bottom`` set,
        each sample is filled down to that coordinate; otherwise only the
        sampled pixels are drawn.  This keeps history-chart rendering shared
        by styles and avoids one Python-to-framebuf call per screen column.
        """
        if not columns:
            return
        if bottom is None:
            previous = None
            run_start = None
            for x, y, color in columns:
                current = (y, color)
                if previous is not None and current != previous:
                    self.fill_rect(
                        run_start, previous[0], x - run_start,
                        1, previous[1],
                    )
                    run_start = x
                elif previous is None:
                    run_start = x
                previous = current
            self.fill_rect(
                run_start, previous[0],
                columns[-1][0] - run_start + 1, 1, previous[1],
            )
            return

        start = 0
        count = len(columns)
        while start < count:
            color = columns[start][2]
            end = start + 1
            while end < count and columns[end][2] == color:
                end += 1
            segment = columns[start:end]
            if len(segment) == 1:
                x, top, _ = segment[0]
                self.fill_rect(x, top, 1, bottom - top + 1, color)
            else:
                # 面积图按列填充，避免尖峰和深谷形成的凹多边形漏掉内部像素。
                self._draw_column_fallback(segment, bottom, color)
            start = end

    def draw_line_chart(self, definition, values):
        """按照图表定义绘制折线图，作为原生 C 组件的兼容策略。"""
        x = int(definition.get("x", 0))
        y = int(definition.get("y", 0))
        width = int(definition.get("width", 0))
        height = int(definition.get("height", 0))
        grid_step_x = int(definition.get("grid_step_x", 0))
        grid_step_y = int(definition.get("grid_step_y", 0))
        grid_color = int(definition.get("grid_color", 0))
        if grid_step_x > 0 and grid_step_y > 0:
            self.draw_grid(
                x, y, width, height,
                grid_step_x, grid_step_y, grid_color,
            )
        if width <= 0 or height <= 0 or not values or len(values) < 2:
            return
        normalized_values = []
        for value in values:
            try:
                normalized_values.append(float(value))
            except (TypeError, ValueError):
                normalized_values.append(0.0)
        maximum = float(definition.get("maximum", 0) or 0)
        if maximum <= 0:
            maximum = max(1, max(normalized_values))
        default_color = int(definition.get("color", 0xFFFF))
        regions = definition.get("regions") or ()
        color_callback = definition.get("color_callback")
        color_cache_step = float(definition.get("color_cache_step", 1) or 0)
        color_cache = {}
        filled = bool(definition.get("filled", False))
        bottom = y + height - 1
        columns = []
        last_index = len(normalized_values) - 1
        divisor = max(1, width - 1)
        for offset_x in range(width):
            scaled = offset_x * last_index
            left_index = min(last_index, scaled // divisor)
            right_index = min(last_index, left_index + 1)
            remainder = scaled % divisor
            value = normalized_values[left_index] + (
                normalized_values[right_index] - normalized_values[left_index]
            ) * remainder / divisor
            value = max(0, min(maximum, value))
            point_y = bottom - int(value * (height - 1) / maximum)
            color = default_color
            if callable(color_callback):
                if color_cache_step > 0:
                    cache_bucket = int(value / color_cache_step)
                    if cache_bucket not in color_cache:
                        color_cache[cache_bucket] = int(color_callback(value))
                    color = color_cache[cache_bucket]
                else:
                    color = int(color_callback(value))
            else:
                for upper_limit, region_color in regions:
                    if value < upper_limit:
                        color = region_color
                        break
            columns.append((x + offset_x, point_y, color))
        if filled:
            self.draw_columns(columns, bottom)
            return
        previous = columns[0]
        for point in columns[1:]:
            self.line(
                previous[0], previous[1], point[0], point[1], point[2]
            )
            previous = point

    def _draw_column_fallback(self, columns, bottom, color):
        """Draw columns on firmware without ``FrameBuffer.poly`` support."""
        run_x, run_top = columns[0][0], columns[0][1]
        previous_x = run_x
        for x, top, _ in columns[1:]:
            if top != run_top or x != previous_x + 1:
                self.fill_rect(
                    run_x, run_top, previous_x - run_x + 1,
                    bottom - run_top + 1, color,
                )
                run_x, run_top = x, top
            previous_x = x
        self.fill_rect(
            run_x, run_top, previous_x - run_x + 1,
            bottom - run_top + 1, color,
        )

    def text(self, x, y, value, color, scale=1, font_name=None):
        """使用默认或指定点阵字体绘制文本，调用后恢复默认字体。"""
        previous = self._select_text_font(font_name)
        try:
            self._draw_text(x, y, value, color, scale)
        finally:
            self._restore_text_font(previous)

    def _draw_text(self, x, y, value, color, scale):
        """使用当前已选字体绘制文本并按实际字形宽度推进光标。"""
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
            self._blit_cached_text(x, y, value, color, scale)
            return
        if self._framebuffer is not None and scale > 1:
            self._blit_cached_text(x, y, value, color, scale)
            return
        cursor_x = x
        for character in value:
            columns = self._font_glyph(character)
            for column_index, bits in enumerate(columns):
                for row_index in range(self._font_height()):
                    if bits & (1 << row_index):
                        self.fill_rect(
                            cursor_x + column_index * scale,
                            y + row_index * scale,
                            scale, scale, color,
                        )
            cursor_x += self._character_advance(character, scale)

    def _blit_cached_text(self, x, y, value, color, scale):
        """为非原生字体复制容量受限的整段文字位图缓存。"""
        if len(value) < 2 or MAX_TEXT_CACHE_BYTES <= 0:
            if scale == 1:
                self._blit_font_text(x, y, value, color)
            else:
                self._blit_scaled_text(x, y, value, color, scale)
            return
        key = (self._font_name, value, scale)
        cached = self._text_cache.pop(key, None)
        if cached is not None:
            self._text_cache[key] = cached
            bitmap, _ = cached
        else:
            width = self.text_width(value, scale)
            height = self._font_height() * scale
            size = ((width + 7) // 8) * height
            seen_count = self._text_seen.get(key, 0) + 1
            if (
                len(self._text_seen) >= MAX_TEXT_SEEN_KEYS
                and key not in self._text_seen
            ):
                oldest_seen = next(iter(self._text_seen))
                del self._text_seen[oldest_seen]
            self._text_seen[key] = seen_count
            dynamic_text = any("0" <= character <= "9" for character in value)
            if (
                size > MAX_TEXT_BITMAP_BYTES
                or seen_count < 2
                or dynamic_text
                or self._text_cache_bytes + size > MAX_TEXT_CACHE_BYTES
            ):
                if scale == 1:
                    self._blit_font_text(x, y, value, color)
                else:
                    self._blit_scaled_text(x, y, value, color, scale)
                return
            bitmap_buffer = None
            try:
                bitmap_buffer = bytearray(size)
                bitmap = framebuf.FrameBuffer(
                    bitmap_buffer, width, height, framebuf.MONO_HLSB
                )
                bitmap.fill(0)
                cursor_x = 0
                for character in value:
                    glyph = self._get_scaled_glyph(character, scale)
                    offset = (
                        1
                        if scale == 1 and self._font_name == "screen_2inch"
                        else 0
                    )
                    bitmap.blit(glyph, cursor_x + offset, 0, 0)
                    cursor_x += self._character_advance(character, scale)
            except MemoryError:
                bitmap_buffer = None
                self._text_seen[key] = 0
                try:
                    if scale == 1:
                        self._blit_font_text(x, y, value, color)
                    else:
                        self._blit_scaled_text(x, y, value, color, scale)
                except MemoryError:
                    # A missing label is preferable to aborting the protocol.
                    pass
                return
            self._text_cache[key] = (bitmap, size)
            self._text_cache_bytes += size
        self._framebuffer.blit(
            bitmap, x - self.origin_x, y - self.origin_y,
            self._native_color(BLACK), self._get_text_palette(color),
        )

    def text_width(self, value, scale=1, font_name=None):
        """根据默认或指定字体计算文本占用像素宽度。"""
        previous = self._select_text_font(font_name)
        try:
            return sum(
                self._character_advance(character, scale)
                for character in str(value)
            )
        finally:
            self._restore_text_font(previous)

    def _character_advance(self, character, scale=1):
        """返回单个字符的水平步进，宽字形会自动扩展间距。"""
        advance = getattr(self._font, "advance", None)
        if callable(advance):
            return advance(character) * scale
        columns = self._font_glyph(character)
        if self._font_name == "screen_2inch_compact":
            return (len(columns) + 1) * scale
        if scale == 1 and self._font_name != "native":
            return max(8, len(columns) + 1)
        return max(6, len(columns) + 1) * scale

    def _font_height(self):
        """返回当前字体的字形画布高度。"""
        return int(getattr(self._font, "height", 7))

    def _font_glyph(self, character):
        """读取当前字体字形，并在字典字体缺字时回退为问号。"""
        if hasattr(self._font, "glyph"):
            return self._font.glyph(character)
        return self._font.get(character, self._font["?"])

    def _blit_font_text(self, x, y, value, color):
        """按照原生字符间距绘制当前样式选择的点阵字体。"""
        cursor_x = x
        palette = self._get_text_palette(color)
        for character in value:
            glyph = self._get_scaled_glyph(character, 1)
            offset = 1 if self._font_name == "screen_2inch" else 0
            self._framebuffer.blit(
                glyph,
                cursor_x + offset - self.origin_x,
                y - self.origin_y,
                self._native_color(BLACK),
                palette,
            )
            cursor_x += self._character_advance(character, 1)

    def _blit_scaled_text(self, x, y, value, color, scale):
        """使用缓存字形快速绘制放大文本。"""
        cursor_x = x
        palette = self._get_text_palette(color)
        for character in value:
            glyph = self._get_scaled_glyph(character, scale)
            self._framebuffer.blit(
                glyph,
                cursor_x - self.origin_x,
                y - self.origin_y,
                self._native_color(BLACK),
                palette,
            )
            cursor_x += self._character_advance(character, scale)

    def _get_scaled_glyph(self, character, scale):
        """获取或创建指定字符的原生放大字形缓存。"""
        key = (self._font_name, character, scale)
        glyph = self._glyph_cache.get(key)
        if glyph is not None:
            return glyph
        if len(self._glyph_cache) >= MAX_GLYPH_CACHE_SIZE:
            # 仅淘汰一个旧字形，避免缓存达到上限时整表失效并在同一帧内
            # 重新生成大量仍会重复使用的字形。
            oldest_key = next(iter(self._glyph_cache))
            del self._glyph_cache[oldest_key]
        columns = self._font_glyph(character)
        width = max(6, len(columns)) * scale
        height = self._font_height() * scale
        glyph_buffer = bytearray(((width + 7) // 8) * height)
        glyph = framebuf.FrameBuffer(
            glyph_buffer,
            width,
            height,
            framebuf.MONO_HLSB,
        )
        glyph.fill(0)
        for column_index, bits in enumerate(columns):
            for row_index in range(self._font_height()):
                if bits & (1 << row_index):
                    glyph.fill_rect(
                        column_index * scale,
                        row_index * scale,
                        scale,
                        scale,
                        1,
                    )
        self._glyph_cache[key] = glyph
        return glyph

    def _get_text_palette(self, color):
        """Return a tiny RGB565 palette mapping monochrome text to color."""
        palette = self._palette_cache.get(color)
        if palette is not None:
            return palette
        palette_buffer = bytearray(4)
        palette = framebuf.FrameBuffer(
            palette_buffer, 2, 1, framebuf.RGB565
        )
        palette.pixel(0, 0, self._native_color(BLACK))
        palette.pixel(1, 0, self._native_color(color))
        self._palette_cache[color] = palette
        return palette
