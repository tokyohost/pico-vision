"""将系统 JSON 快照按可见区域渲染到 Pico LCD。"""

import time

from canvas import Canvas
from config import (
    BLACK, BLUE, DARK, GRAY, GREEN, HEIGHT, LCD_STRIP_HEIGHT,
    PURPLE, RED, WHITE, WIDTH, YELLOW,
)


class DashboardRenderer:
    """使用条带缓冲和区域裁剪渲染 240×320 仪表盘。"""

    def __init__(self, lcd):
        """创建条带画布并初始化渲染状态。"""
        self.lcd = lcd
        self.canvas = Canvas(WIDTH, LCD_STRIP_HEIGHT)
        self._snapshot = None
        self._next_y = HEIGHT
        self._render_started = None
        self._last_render_ms = 0
        self._canvas_us = 0
        self._lcd_us = 0
        self._region_count = 0
        self._initialized = False
        self._dirty_regions = []
        self._dirty_index = 0

    def request_render(self, snapshot):
        """登记快照并从屏幕顶部开始新一帧。"""
        self._snapshot = snapshot or {}
        if self._initialized:
            self._next_y = HEIGHT
            self._dirty_regions = self._create_dirty_regions()
            self._dirty_index = 0
        else:
            self._next_y = 0
            self._dirty_regions = []
        self._render_started = time.ticks_ms()
        self._canvas_us = 0
        self._lcd_us = 0
        self._region_count = 0

    def is_rendering(self):
        """判断当前帧是否仍有条带尚未写屏。"""
        return self._next_y < HEIGHT or self._dirty_index < len(self._dirty_regions)

    def update(self):
        """仅绘制一个条带，并在整帧完成时返回真。"""
        if not self.is_rendering():
            return False
        if self._next_y < HEIGHT:
            strip_height = min(LCD_STRIP_HEIGHT, HEIGHT - self._next_y)
            self.canvas.set_view(0, self._next_y, WIDTH, strip_height)
            canvas_started = time.ticks_us()
            self._draw_visible(self._snapshot)
            self._canvas_us += time.ticks_diff(
                time.ticks_us(), canvas_started
            )
            lcd_started = time.ticks_us()
            self._show_view(0, self._next_y, WIDTH, strip_height)
            self._lcd_us += time.ticks_diff(time.ticks_us(), lcd_started)
            self._region_count += 1
            self._next_y += strip_height
            if self._next_y >= HEIGHT:
                self._initialized = True
        else:
            key, x, y, width, height = self._dirty_regions[self._dirty_index]
            self.canvas.set_view(x, y, width, height)
            canvas_started = time.ticks_us()
            self._draw_dirty(key, self._snapshot)
            self._canvas_us += time.ticks_diff(
                time.ticks_us(), canvas_started
            )
            lcd_started = time.ticks_us()
            self._show_view(x, y, width, height)
            self._lcd_us += time.ticks_diff(time.ticks_us(), lcd_started)
            self._region_count += 1
            self._dirty_index += 1
        completed = not self.is_rendering()
        if completed:
            self._last_render_ms = time.ticks_diff(
                time.ticks_ms(), self._render_started
            )
            self._render_started = None
        return completed

    def _show_view(self, x, y, width, height):
        """将当前视口的有效像素提交到 LCD。"""
        byte_count = width * height * 2
        self.lcd.show_region(
            x, y, width, height,
            memoryview(self.canvas.buffer)[:byte_count],
        )

    @staticmethod
    def _create_dirty_regions():
        """创建每帧需要刷新的动态区域列表。"""
        regions = [("status_light", 219, 10, 12, 12)]
        for name, y in (("cpu", 43), ("memory", 100), ("disk", 157)):
            regions.append((name + "_value", 94, y, 70, 14))
            regions.append((name + "_detail", 8, y + 22, 105, 22))
            regions.append((name + "_history", 126, y + 18, 105, 27))
        regions.append(("network_rate", 8, 245, 223, 8))
        regions.append(("network_status", 8, 261, 223, 8))
        regions.append(("footer", 8, 292, 223, 14))
        return regions

    def last_render_ms(self):
        """返回最近一帧从开始到完成的耗时毫秒数。"""
        return self._last_render_ms

    def last_profile(self):
        """返回最近一帧画布、LCD 和区域数量性能统计。"""
        return self._canvas_us, self._lcd_us, self._region_count

    def _visible(self, top, bottom):
        """判断纵向区域是否与当前条带相交。"""
        strip_top = self.canvas.origin_y
        strip_bottom = strip_top + self.canvas.height
        return top < strip_bottom and bottom > strip_top

    @staticmethod
    def _number(value, default=0):
        """安全地将 JSON 数值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _format_bytes(value):
        """将字节数格式化为适合屏幕显示的短文本。"""
        amount = DashboardRenderer._number(value)
        for unit in ("B", "K", "M", "G", "T"):
            if amount < 1024 or unit == "T":
                return "{:.1f}{}".format(amount, unit) if unit in ("G", "T") else "{:.0f}{}".format(amount, unit)
            amount /= 1024
        return "0B"

    @staticmethod
    def _format_uptime(seconds):
        """将运行秒数格式化为天、小时和分钟。"""
        minutes = int(DashboardRenderer._number(seconds)) // 60
        days, remainder = divmod(minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}".format(days, hours, minutes)

    def _draw_bar(self, x, y, width, height, percent, color):
        """绘制百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        self.canvas.fill_rect(x, y, width, height, DARK)
        self.canvas.fill_rect(x + 1, y + 1, int((width - 2) * value / 100), height - 2, color)

    def _draw_history(self, x, y, width, height, values, color):
        """绘制百分比历史折线。"""
        if not values or len(values) < 2:
            return
        previous = None
        count = len(values)
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (count - 1))
            ratio = max(0, min(1, self._number(value) / 100))
            point = (point_x, y + height - 1 - int(ratio * (height - 1)))
            if previous is not None:
                self.canvas.line(previous[0], previous[1], point[0], point[1], color)
            previous = point

    def _draw_metric(self, y, title, data, color, detail):
        """绘制单个 CPU、内存或磁盘指标区域。"""
        percent = data.get("percent")
        self.canvas.text(8, y, title, color, 2)
        self.canvas.text(94, y, "{}%".format(int(self._number(percent))), WHITE, 2)
        self.canvas.text(8, y + 22, detail, GRAY, 1)
        self._draw_bar(8, y + 34, 105, 10, percent, color)
        self._draw_history(126, y + 18, 105, 27, data.get("history", ()), color)

    def _draw_dirty(self, key, snapshot):
        """清空并重绘一个动态脏矩形。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        self.canvas.clear(BLACK)

        if key == "status_light":
            self.canvas.fill_rect(219, 10, 12, 12, GREEN if network.get("online") else RED)
            return
        if key == "network_rate":
            self.canvas.text(8, 245, "UP " + self._format_bytes(network.get("upload_bps")) + "/S", BLUE, 1)
            self.canvas.text(122, 245, "DN " + self._format_bytes(network.get("download_bps")) + "/S", GREEN, 1)
            return
        if key == "network_status":
            ping = network.get("ping_ms")
            ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
            self.canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
            self.canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)
            return
        if key == "footer":
            timestamp = str(snapshot.get("timestamp", ""))
            clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
            self.canvas.text(8, 292, clock, WHITE, 2)
            self.canvas.text(116, 294, self._format_uptime(snapshot.get("uptime_seconds")), GRAY, 1)
            return

        name, part = key.rsplit("_", 1)
        if name == "cpu":
            data, y, color = cpu, 43, BLUE
            temperature = data.get("temperature_c")
            detail = "TEMP " + ("--C" if temperature is None else "{}C".format(int(self._number(temperature))))
        elif name == "memory":
            data, y, color = memory, 100, GREEN
            detail = self._format_bytes(data.get("used_bytes")) + "/" + self._format_bytes(data.get("total_bytes"))
        else:
            data, y, color = disk, 157, YELLOW
            detail = self._format_bytes(data.get("used_bytes")) + "/" + self._format_bytes(data.get("total_bytes"))

        if part == "value":
            self.canvas.text(94, y, "{}%".format(int(self._number(data.get("percent")))), WHITE, 2)
        elif part == "detail":
            self.canvas.text(8, y + 22, detail, GRAY, 1)
            self._draw_bar(8, y + 34, 105, 10, data.get("percent"), color)
        else:
            self._draw_history(126, y + 18, 105, 27, data.get("history", ()), color)

    def _draw_visible(self, snapshot):
        """只执行与当前条带相交的仪表盘绘制逻辑。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        self.canvas.clear(BLACK)

        if self._visible(0, 35):
            self.canvas.text(8, 8, str(snapshot.get("host", "WAITING"))[:18], WHITE, 2)
            self.canvas.fill_rect(219, 10, 12, 12, GREEN if network.get("online") else RED)
            self.canvas.line(0, 34, WIDTH - 1, 34, GRAY)

        if self._visible(43, 88):
            temperature = cpu.get("temperature_c")
            text = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
            self._draw_metric(43, "CPU", cpu, BLUE, "TEMP " + text)
        if self._visible(100, 145):
            detail = self._format_bytes(memory.get("used_bytes")) + "/" + self._format_bytes(memory.get("total_bytes"))
            self._draw_metric(100, "RAM", memory, GREEN, detail)
        if self._visible(157, 202):
            detail = self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes"))
            self._draw_metric(157, "DISK", disk, YELLOW, detail)

        if self._visible(213, 280):
            self.canvas.line(0, 213, WIDTH - 1, 213, GRAY)
            self.canvas.text(8, 222, "NET", PURPLE, 2)
            self.canvas.text(8, 245, "UP " + self._format_bytes(network.get("upload_bps")) + "/S", BLUE, 1)
            self.canvas.text(122, 245, "DN " + self._format_bytes(network.get("download_bps")) + "/S", GREEN, 1)
            ping = network.get("ping_ms")
            ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
            self.canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
            self.canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)

        if self._visible(280, HEIGHT):
            self.canvas.line(0, 280, WIDTH - 1, 280, GRAY)
            timestamp = str(snapshot.get("timestamp", ""))
            clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
            self.canvas.text(8, 292, clock, WHITE, 2)
            self.canvas.text(116, 294, self._format_uptime(snapshot.get("uptime_seconds")), GRAY, 1)
