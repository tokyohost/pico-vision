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



"""使用可插拔样式将系统快照按可见区域渲染到 Pico LCD。"""


import gc
import time

from canvas import Canvas
from config import HEIGHT, LCD_STRIP_HEIGHT, LCD_STYLE, WIDTH
from styles.style_plugins import create_style, normalize_style_name, release_style


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
        self._completion_pending = False

    def style_name(self):
        """返回当前生效的样式插件名称。"""
        return self._style_name

    def set_style(self, style_name):
        """切换样式插件，并要求下一次渲染执行完整刷新。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        self.canvas.clear_glyph_cache()
        gc.collect()
        previous_style_name = self._style_name
        style = create_style(normalized_name)
        self._style = style
        self._style_name = style.name
        self._apply_style_geometry()
        self._initialized = False
        release_style(previous_style_name)
        gc.collect()
        return True

    def _apply_style_geometry(self):
        """应用样式声明的画布尺寸和 LCD 横竖屏方向。"""
        self._width = int(getattr(self._style, "width", WIDTH))
        self._height = int(getattr(self._style, "height", HEIGHT))
        required_pixels = self._width * LCD_STRIP_HEIGHT
        current_canvas = getattr(self, "canvas", None)
        if (
            current_canvas is not None
            and current_canvas._capacity_pixels >= required_pixels
        ):
            self.canvas = current_canvas
            self.canvas.set_view(
                0, 0, self._width,
                min(LCD_STRIP_HEIGHT, self._height),
            )
        else:
            if current_canvas is not None:
                self.canvas = None
                del current_canvas
                gc.collect()
            self.canvas = Canvas(self._width, LCD_STRIP_HEIGHT)
        self.canvas.set_font(getattr(self._style, "font_name", "native"))
        self.lcd.set_landscape(bool(getattr(self._style, "landscape", False)))

    def set_rotation(self, rotation):
        """切换方向后按新扫描方向清屏，并要求下一帧完整刷新。"""
        normalized = 180 if rotation == 180 else 0
        if normalized == self.lcd.rotation():
            return False
        self.lcd.set_display_enabled(False)
        try:
            changed = self.lcd.set_rotation(normalized)
            self._clear_screen()
        finally:
            self.lcd.set_display_enabled(True)
        if changed:
            self._initialized = False
        return changed

    def _clear_screen(self):
        """按当前屏幕方向分条带写入黑色，避免旋转后残留旧画面。"""
        strip_height = min(LCD_STRIP_HEIGHT, self._height)
        black_strip = bytes(self._width * strip_height * 2)
        y = 0
        while y < self._height:
            height = min(strip_height, self._height - y)
            byte_count = self._width * height * 2
            self.lcd.show_region(
                0,
                y,
                self._width,
                height,
                memoryview(black_strip)[:byte_count],
            )
            y += height

    def request_render(self, snapshot, force=False):
        """登记快照，并按差异刷新或强制刷新动态区域。"""
        next_snapshot = snapshot or {}
        begin_frame = getattr(self._style, "begin_frame", None)
        if callable(begin_frame):
            begin_frame()
        if self._initialized:
            self._next_y = self._height
            selector = getattr(self._style, "select_dirty_regions", None)
            if force:
                self._dirty_regions = self._style.create_dirty_regions()
            elif callable(selector):
                self._dirty_regions = selector(
                    self._snapshot or {}, next_snapshot
                )
            else:
                self._dirty_regions = self._style.create_dirty_regions()
            self._dirty_index = 0
        else:
            self._next_y = 0
            self._dirty_regions = []
        self._snapshot = next_snapshot
        self._render_started = time.ticks_ms()
        self._completion_pending = True
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
            self._completion_pending = False
            # 一帧绘制会产生较多短命对象，及时整理堆以便接收下一包 JSON。
            gc.collect()
        return completed

    def update_pending(self, max_regions=8):
        """在单轮循环内批量刷新多个区域，减少区域间的调度延迟。"""
        if not self.is_rendering() and self._completion_pending:
            self._last_render_ms = time.ticks_diff(
                time.ticks_ms(), self._render_started
            )
            self._render_started = None
            self._completion_pending = False
            return True
        updated = 0
        while updated < max_regions and self.is_rendering():
            updated += 1
            if self.update():
                return True
        return False

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
