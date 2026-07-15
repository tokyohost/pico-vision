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

"""在完整 RAM 画布绘制界面，并把脏区检测与条带发送交给 C 固件。"""

import gc
import time

from canvas_backend import Canvas, canvas_backend_name
from config import BLACK, LCD_STYLE
from styles.style_plugins import create_style, normalize_style_name, release_style


class DashboardRenderer:
    """维护完整 RGB565 画布，并将每帧一次性提交给原生 LCD 后端。"""

    def __init__(self, lcd, style_name=LCD_STYLE):
        """创建样式和完整画布，不再让 MicroPython 分条带重复绘制。"""
        self.lcd = lcd
        self._style = create_style(style_name)
        self._style_name = self._style.name
        self.canvas = None
        self._snapshot = None
        self._frame_pending = False
        self._force_frame = True
        self._render_started = None
        self._last_render_ms = 0
        self._canvas_us = 0
        self._view_us = 0
        self._buffer_us = 0
        self._lcd_us = 0
        self._gc_us = 0
        self._slowest_region_us = 0
        self._region_count = 0
        self._completion_pending = False
        self._apply_style_geometry()

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
        """预加载并注册指定样式，但保持当前画布和显示内容不变。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        style = create_style(normalized_name)
        del style
        gc.collect()
        return True

    def set_style(self, style_name):
        """释放旧样式后加载新样式，并按新方向重建完整画布。"""
        normalized_name = normalize_style_name(style_name)
        if normalized_name == self._style_name:
            return False
        self.canvas.clear_glyph_cache()
        previous_style_name = self._style_name
        self.abort_render(release_snapshot=True)
        self._style = None
        release_style(previous_style_name)
        gc.collect()
        try:
            style = create_style(normalized_name)
        except Exception:
            release_style(normalized_name)
            gc.collect()
            if normalized_name != "boot":
                style = create_style("boot")
                self._style = style
                self._style_name = style.name
                self._apply_style_geometry()
            raise
        self._style = style
        self._style_name = style.name
        self._apply_style_geometry()
        self._force_frame = True
        gc.collect()
        return True

    def abort_render(self, release_snapshot=False):
        """中止尚未绘制的帧，并可同时释放帧快照引用。"""
        self._frame_pending = False
        self._render_started = None
        self._completion_pending = False
        if release_snapshot:
            self._snapshot = None

    def _apply_style_geometry(self):
        """按样式方向分配完整画布，并同步 C 固件的逻辑屏幕尺寸。"""
        panel_profile = self.lcd.panel_profile
        width = int(getattr(self._style, "width", panel_profile.width))
        height = int(getattr(self._style, "height", panel_profile.height))
        landscape = bool(getattr(self._style, "landscape", False))
        self.lcd.set_landscape(landscape)
        self.lcd.configure_canvas(width, height)
        required_pixels = width * height
        current_canvas = self.canvas
        if (
            current_canvas is None
            or current_canvas._capacity_pixels < required_pixels
        ):
            self.canvas = None
            if current_canvas is not None:
                del current_canvas
                gc.collect()
            self.canvas = Canvas(width, height)
        else:
            self.canvas.set_view(0, 0, width, height)
        self._width = width
        self._height = height
        self.canvas.set_font(getattr(self._style, "font_name", "native"))

    def set_rotation(self, rotation):
        """切换扫描方向、清空显示并强制下一帧建立新的脏区基线。"""
        normalized = 180 if rotation == 180 else 0
        if normalized == self.lcd.rotation():
            return False
        self.lcd.set_display_enabled(False)
        try:
            changed = self.lcd.set_rotation(normalized)
            self._clear_screen()
        finally:
            self.lcd.set_display_enabled(True)
        self._force_frame = bool(changed)
        return changed

    def _clear_screen(self):
        """直接清空完整画布，并通过 C 固件强制提交一次全屏。"""
        self.canvas.set_view(0, 0, self._width, self._height)
        self.canvas.clear(BLACK)
        self.lcd.present(self.canvas.buffer, force=True)

    def request_render(self, snapshot, force=False):
        """登记最新快照，实际绘制始终发生在完整 RAM 画布。"""
        next_snapshot = dict(snapshot) if snapshot else {}
        begin_frame = getattr(self._style, "begin_frame", None)
        if callable(begin_frame):
            begin_frame()
        prepare_frame = getattr(self._style, "prepare_frame", None)
        if callable(prepare_frame):
            prepare_frame(next_snapshot)
        self._snapshot = next_snapshot
        self._force_frame = self._force_frame or bool(force)
        self._frame_pending = True
        self._completion_pending = True
        self._render_started = time.ticks_ms()
        self._canvas_us = 0
        self._view_us = 0
        self._buffer_us = 0
        self._lcd_us = 0
        self._gc_us = 0
        self._slowest_region_us = 0
        self._region_count = 0

    def is_rendering(self):
        """返回当前是否有一帧完整画布等待绘制和提交。"""
        return self._frame_pending

    def update(self):
        """绘制一次完整画布，由 C 固件检测脏区并只发送变化区域。"""
        if not self._frame_pending:
            return False
        frame_started = time.ticks_us()
        self.canvas.set_view(0, 0, self._width, self._height)
        canvas_started = time.ticks_us()
        self._style.draw_visible(self.canvas, self._snapshot)
        self._canvas_us = time.ticks_diff(time.ticks_us(), canvas_started)
        lcd_started = time.ticks_us()
        self._region_count = self.lcd.present(
            self.canvas.buffer, force=self._force_frame
        )
        self._lcd_us = time.ticks_diff(time.ticks_us(), lcd_started)
        self._slowest_region_us = self._lcd_us
        self._force_frame = False
        self._frame_pending = False
        self._completion_pending = False
        self._last_render_ms = time.ticks_diff(
            time.ticks_ms(), self._render_started
        )
        self._render_started = None
        self._buffer_us = max(
            0,
            time.ticks_diff(time.ticks_us(), frame_started)
            - self._canvas_us - self._lcd_us,
        )
        return True

    def record_gc_us(self, elapsed_us):
        """记录应用在当前帧完成后安全执行垃圾回收的耗时。"""
        self._gc_us = max(0, int(elapsed_us))

    def update_pending(self, max_regions=8, time_budget_us=None):
        """兼容旧调度接口；完整画布模式每次最多提交一帧。"""
        del max_regions, time_budget_us
        return self.update()

    def capture_screen(self, chunk_writer, rows_per_chunk=8):
        """从当前完整画布直接分行输出截图，无需重新执行样式绘制。"""
        if self._snapshot is None:
            raise ValueError("当前没有可截图的 LCD 画面")
        rows_per_chunk = max(1, min(int(rows_per_chunk), self._height))
        sequence = 0
        row_bytes = self._width * 2
        y = 0
        view = memoryview(self.canvas.buffer)
        while y < self._height:
            height = min(rows_per_chunk, self._height - y)
            start = y * row_bytes
            chunk_writer(
                sequence,
                y,
                height,
                view[start:start + height * row_bytes],
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
        """返回最近一帧画布、LCD 和 C 固件脏区数量统计。"""
        return self._canvas_us, self._lcd_us, self._region_count

    def last_detailed_profile(self):
        """返回最近一帧完整画布绘制与增量发送的详细统计。"""
        measured_us = self._canvas_us + self._buffer_us + self._lcd_us
        total_us = self._last_render_ms * 1000
        return {
            "view_us": self._view_us,
            "canvas_us": self._canvas_us,
            "buffer_us": max(0, self._buffer_us),
            "lcd_us": self._lcd_us,
            "gc_us": self._gc_us,
            "schedule_us": max(0, total_us - measured_us),
            "slowest_region_us": self._slowest_region_us,
            "region_count": self._region_count,
        }
