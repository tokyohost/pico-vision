"""使用可插拔样式将系统快照按可见区域渲染到 Pico LCD。"""

import time

from canvas import Canvas
from config import HEIGHT, LCD_STRIP_HEIGHT, LCD_STYLE, WIDTH
from style_plugins import create_style, normalize_style_name


class DashboardRenderer:
    """负责通用条带调度，并将具体界面绘制委托给样式插件。"""

    def __init__(self, lcd, style_name=LCD_STYLE):
        """创建条带画布并加载配置指定的样式插件。"""
        self.lcd = lcd
        self._style = create_style(style_name)
        self._style_name = self._style.name
        self._apply_style_geometry()
        self._snapshot = None
        self._next_y = self._height
        self._render_started = None
        self._last_render_ms = 0
        self._canvas_us = 0
        self._lcd_us = 0
        self._region_count = 0
        self._initialized = False
        self._dirty_regions = []
        self._dirty_index = 0

    def style_name(self):
        """返回当前生效的样式插件名称。"""
        return self._style_name

    def set_style(self, style_name):
        """切换样式插件，并要求下一次渲染执行完整刷新。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        style = create_style(normalized_name)
        self._style = style
        self._style_name = style.name
        self._apply_style_geometry()
        self._initialized = False
        return True

    def _apply_style_geometry(self):
        """应用样式声明的画布尺寸和 LCD 横竖屏方向。"""
        self._width = int(getattr(self._style, "width", WIDTH))
        self._height = int(getattr(self._style, "height", HEIGHT))
        self.canvas = Canvas(self._width, LCD_STRIP_HEIGHT)
        self.canvas.set_font(getattr(self._style, "font_name", "native"))
        self.lcd.set_landscape(bool(getattr(self._style, "landscape", False)))

    def set_rotation(self, rotation):
        """按当前样式方向设置屏幕正向或反向显示。"""
        return self.lcd.set_rotation(rotation)

    def request_render(self, snapshot):
        """登记快照并准备完整刷新或动态区域刷新。"""
        self._snapshot = snapshot or {}
        if self._initialized:
            self._next_y = self._height
            self._dirty_regions = self._style.create_dirty_regions()
            self._dirty_index = 0
        else:
            self._next_y = 0
            self._dirty_regions = []
        self._render_started = time.ticks_ms()
        self._canvas_us = 0
        self._lcd_us = 0
        self._region_count = 0

    def is_rendering(self):
        """判断当前帧是否仍有条带或动态区域尚未写屏。"""
        return self._next_y < self._height or self._dirty_index < len(self._dirty_regions)

    def update(self):
        """仅绘制一个条带或动态区域，并在整帧完成时返回真。"""
        if not self.is_rendering():
            return False
        if self._next_y < self._height:
            x, y, width = 0, self._next_y, self._width
            height = min(LCD_STRIP_HEIGHT, self._height - y)
            self.canvas.set_view(x, y, width, height)
            canvas_started = time.ticks_us()
            self._style.draw_visible(self.canvas, self._snapshot)
        else:
            key, x, y, width, height = self._dirty_regions[self._dirty_index]
            self.canvas.set_view(x, y, width, height)
            canvas_started = time.ticks_us()
            self._style.draw_dirty(self.canvas, key, self._snapshot)
        self._canvas_us += time.ticks_diff(time.ticks_us(), canvas_started)
        lcd_started = time.ticks_us()
        self._show_view(x, y, width, height)
        self._lcd_us += time.ticks_diff(time.ticks_us(), lcd_started)
        self._region_count += 1
        if self._next_y < self._height:
            self._next_y += height
            if self._next_y >= self._height:
                self._initialized = True
        else:
            self._dirty_index += 1
        completed = not self.is_rendering()
        if completed:
            self._last_render_ms = time.ticks_diff(time.ticks_ms(), self._render_started)
            self._render_started = None
        return completed

    def _show_view(self, x, y, width, height):
        """将当前视口的有效像素提交到 LCD。"""
        byte_count = width * height * 2
        self.lcd.show_region(x, y, width, height, memoryview(self.canvas.buffer)[:byte_count])

    def last_render_ms(self):
        """返回最近一帧从开始到完成的耗时毫秒数。"""
        return self._last_render_ms

    def last_profile(self):
        """返回最近一帧画布、LCD 和区域数量性能统计。"""
        return self._canvas_us, self._lcd_us, self._region_count
