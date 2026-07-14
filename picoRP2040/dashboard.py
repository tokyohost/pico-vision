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

from canvas_backend import Canvas, canvas_backend_name
from config import (
    BLACK,
    LCD_STRIP_HEIGHT,
    LCD_STYLE,
)
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
        self._view_us = 0
        self._buffer_us = 0
        self._lcd_us = 0
        self._gc_us = 0
        self._slowest_region_us = 0
        self._region_count = 0
        self._initialized = False
        self._dirty_regions = []
        self._dirty_index = 0
        self._completion_pending = False

    def style_name(self):
        """返回当前生效的样式插件名称。"""
        return self._style_name

    def style_type(self):
        """返回当前样式声明的 builtin 或 custom 类型。"""
        return getattr(self._style, "type", "builtin")

    def canvas_backend(self):
        """返回当前渲染器使用的 Canvas 后端名称。"""
        return canvas_backend_name()

    def preload_style(self, style_name):
        """预加载并注册指定样式，但保持当前启动页面和画布不变。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        style = create_style(normalized_name)
        del style
        gc.collect()
        return True

    def set_style(self, style_name):
        """分阶段释放旧帧和旧样式后加载新样式，避免切换内存峰值。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        self.canvas.clear_glyph_cache()
        previous_style_name = self._style_name
        # 大型样式模块首次导入时需要编译源码。必须先断开旧样式、快照和
        # 脏区的全部强引用，否则新旧对象会在堆中短暂重叠并耗尽连续内存。
        self.abort_render(release_snapshot=True)
        self._style = None
        release_style(previous_style_name)
        gc.collect()
        try:
            style = create_style(normalized_name)
        except Exception:
            # 目标样式加载失败后尽力恢复轻量启动页，让主循环仍可通信和重试。
            release_style(normalized_name)
            gc.collect()
            if normalized_name != "boot":
                style = create_style("boot")
                self._style = style
                self._style_name = style.name
                self._apply_style_geometry()
                self._initialized = False
            raise
        self._style = style
        self._style_name = style.name
        self._apply_style_geometry()
        self._initialized = False
        gc.collect()
        return True

    def abort_render(self, release_snapshot=False):
        """中止当前帧并释放临时区域，可选择同时丢弃帧快照。"""
        self._dirty_regions = []
        self._dirty_index = 0
        self._next_y = self._height
        self._render_started = None
        self._completion_pending = False
        if release_snapshot:
            self._snapshot = None

    def _apply_style_geometry(self):
        """应用样式声明的画布尺寸和 LCD 横竖屏方向。"""
        panel_profile = self.lcd.panel_profile
        self._width = int(getattr(self._style, "width", panel_profile.width))
        self._height = int(getattr(self._style, "height", panel_profile.height))
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
        """复用画布缓冲分条带清屏，避免旋转时触发内存峰值。"""
        strip_height = min(LCD_STRIP_HEIGHT, self._height)
        y = 0
        while y < self._height:
            height = min(strip_height, self._height - y)
            byte_count = self._width * height * 2
            # 旋转发生在样式和字体已经加载后的堆内存高峰期。若重新创建整条
            # 黑色像素数据，RP2040 可能因连续内存不足触发 MemoryError 并复位。
            self.canvas.set_view(0, y, self._width, height)
            self.canvas.clear(BLACK)
            self.lcd.show_region(
                0,
                y,
                self._width,
                height,
                memoryview(self.canvas.buffer)[:byte_count],
            )
            y += height

    def request_render(self, snapshot, force=False):
        """登记快照，并按差异刷新或强制刷新动态区域。"""
        # 时间推进器会原地更新缓存快照。渲染器必须保存独立的帧级根字典，
        # 否则上一帧时间也会被同步改写，差异检测无法发现每秒变化，只能
        # 等到校准或其他区域重绘时才一次跳过多个秒数。
        next_snapshot = dict(snapshot) if snapshot else {}
        begin_frame = getattr(self._style, "begin_frame", None)
        if callable(begin_frame):
            begin_frame()
        prepare_frame = getattr(self._style, "prepare_frame", None)
        if callable(prepare_frame):
            prepare_frame(next_snapshot)
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
        self._view_us = 0
        self._buffer_us = 0
        self._lcd_us = 0
        self._gc_us = 0
        self._slowest_region_us = 0
        self._region_count = 0

    def is_rendering(self):
        """判断当前帧是否仍有条带或动态区域尚未写屏。"""
        return self._next_y < self._height or self._dirty_index < len(self._dirty_regions)

    def update(self):
        """仅绘制一个条带或动态区域，并在整帧完成时返回真。"""
        if not self.is_rendering():
            return False
        region_started = time.ticks_us()
        if self._next_y < self._height:
            x, y, width = 0, self._next_y, self._width
            height = min(LCD_STRIP_HEIGHT, self._height - y)
            view_started = time.ticks_us()
            self.canvas.set_view(x, y, width, height)
            self._view_us += time.ticks_diff(time.ticks_us(), view_started)
            canvas_started = time.ticks_us()
            self._style.draw_visible(self.canvas, self._snapshot)
        else:
            key, x, y, width, height = self._dirty_regions[self._dirty_index]
            view_started = time.ticks_us()
            self.canvas.set_view(x, y, width, height)
            self._view_us += time.ticks_diff(time.ticks_us(), view_started)
            canvas_started = time.ticks_us()
            self._style.draw_dirty(self.canvas, key, self._snapshot)
        self._canvas_us += time.ticks_diff(time.ticks_us(), canvas_started)
        buffer_us, lcd_us = self._show_view(x, y, width, height)
        self._buffer_us += buffer_us
        self._lcd_us += lcd_us
        self._region_count += 1
        region_us = time.ticks_diff(time.ticks_us(), region_started)
        if region_us > self._slowest_region_us:
            self._slowest_region_us = region_us
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
            gc_started = time.ticks_us()
            gc.collect()
            self._gc_us = time.ticks_diff(time.ticks_us(), gc_started)
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
        """将当前视口提交到 LCD，并返回缓冲区准备和写屏耗时。"""
        buffer_started = time.ticks_us()
        byte_count = width * height * 2
        buffer_view = memoryview(self.canvas.buffer)[:byte_count]
        buffer_us = time.ticks_diff(time.ticks_us(), buffer_started)
        lcd_started = time.ticks_us()
        self.lcd.show_region(x, y, width, height, buffer_view)
        lcd_us = time.ticks_diff(time.ticks_us(), lcd_started)
        return buffer_us, lcd_us

    def capture_screen(self, chunk_writer, rows_per_chunk=8):
        """重新绘制当前画面并按 RGB565 条带输出，不额外占用整帧内存。"""
        if self._snapshot is None:
            raise ValueError("当前没有可截图的 LCD 画面")
        rows_per_chunk = max(1, min(int(rows_per_chunk), LCD_STRIP_HEIGHT))
        sequence = 0
        y = 0
        while y < self._height:
            height = min(rows_per_chunk, self._height - y)
            self.canvas.set_view(0, y, self._width, height)
            self._style.draw_visible(self.canvas, self._snapshot)
            byte_count = self._width * height * 2
            chunk_writer(
                sequence,
                y,
                height,
                memoryview(self.canvas.buffer)[:byte_count],
            )
            sequence += 1
            y += height
        return {
            "width": self._width,
            "height": self._height,
            "pixel_format": "RGB565_BE",
            "chunks": sequence,
        }

    def last_render_ms(self):
        """返回最近一帧从开始到完成的耗时毫秒数。"""
        return self._last_render_ms

    def last_profile(self):
        """返回最近一帧画布、LCD 和区域数量性能统计。"""
        return self._canvas_us, self._lcd_us, self._region_count

    def last_detailed_profile(self):
        """返回最近一帧各渲染步骤的详细耗时统计。"""
        measured_us = (
            self._view_us + self._canvas_us + self._buffer_us
            + self._lcd_us
        )
        total_us = self._last_render_ms * 1000
        return {
            "view_us": self._view_us,
            "canvas_us": self._canvas_us,
            "buffer_us": self._buffer_us,
            "lcd_us": self._lcd_us,
            "gc_us": self._gc_us,
            "schedule_us": max(0, total_us - measured_us),
            "slowest_region_us": self._slowest_region_us,
            "region_count": self._region_count,
        }
