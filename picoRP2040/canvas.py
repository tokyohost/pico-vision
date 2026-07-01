"""提供带纵向裁剪的 RGB565 条带绘图能力。"""

from config import BLACK
from font_5x7 import FONT_5X7


class Canvas:
    """在小型条带缓冲区中绘图，坐标仍使用完整屏幕坐标。"""

    def __init__(self, width, height):
        """创建指定大小的 RGB565 条带缓冲区。"""
        self.width = width
        self.height = height
        self.origin_y = 0
        self.buffer = bytearray(width * height * 2)

    def set_origin(self, origin_y):
        """设置当前条带在完整屏幕中的纵向起点。"""
        self.origin_y = origin_y

    @staticmethod
    def _pixel_bytes(color):
        """将 RGB565 整数转换为大端双字节像素。"""
        return bytes(((color >> 8) & 0xFF, color & 0xFF))

    def clear(self, color=BLACK):
        """使用指定颜色清空当前条带。"""
        row = self._pixel_bytes(color) * self.width
        for local_y in range(self.height):
            start = local_y * len(row)
            self.buffer[start:start + len(row)] = row

    def pixel(self, x, y, color):
        """在当前条带范围内绘制一个像素。"""
        local_y = y - self.origin_y
        if 0 <= x < self.width and 0 <= local_y < self.height:
            offset = (local_y * self.width + x) * 2
            self.buffer[offset] = (color >> 8) & 0xFF
            self.buffer[offset + 1] = color & 0xFF

    def fill_rect(self, x, y, width, height, color):
        """绘制经过当前条带边界裁剪的实心矩形。"""
        left = max(0, x)
        top = max(self.origin_y, y)
        right = min(self.width, x + width)
        bottom = min(self.origin_y + self.height, y + height)
        if left >= right or top >= bottom:
            return
        row = self._pixel_bytes(color) * (right - left)
        for line_y in range(top, bottom):
            start = ((line_y - self.origin_y) * self.width + left) * 2
            self.buffer[start:start + len(row)] = row

    def line(self, x0, y0, x1, y1, color):
        """使用整数 Bresenham 算法绘制线段。"""
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
        """使用内置 5×7 点阵字体绘制 ASCII 文本。"""
        cursor_x = x
        for character in str(value).upper():
            columns = FONT_5X7.get(character, FONT_5X7["?"])
            for column_index, bits in enumerate(columns):
                for row_index in range(7):
                    if bits & (1 << row_index):
                        self.fill_rect(
                            cursor_x + column_index * scale,
                            y + row_index * scale,
                            scale, scale, color,
                        )
            cursor_x += 6 * scale
