"""负责将系统 JSON 快照渲染为 Pico 仪表盘。"""

from canvas import Canvas
from config import (
    BLACK,
    BLUE,
    DARK,
    GRAY,
    GREEN,
    HEIGHT,
    LCD_STRIP_HEIGHT,
    PURPLE,
    RED,
    WHITE,
    WIDTH,
    YELLOW,
)


class DashboardRenderer:
    """将系统状态快照绘制为适合 240×320 屏幕的仪表盘。"""

    def __init__(self, lcd):
        """创建渲染画布并保存 LCD 输出设备。"""
        self.lcd = lcd
        self.canvas = Canvas(WIDTH, LCD_STRIP_HEIGHT)
        self._snapshot = None
        self._next_y = HEIGHT

    def request_render(self, snapshot):
        """登记最新快照并从屏幕顶部开始新一轮条带刷新。"""
        self._snapshot = snapshot or {}
        self._next_y = 0

    def update(self):
        """绘制并提交一个屏幕条带，完成后立即返回主循环。"""
        if self._next_y >= HEIGHT:
            return False
        strip_height = min(LCD_STRIP_HEIGHT, HEIGHT - self._next_y)
        self.canvas.set_origin(self._next_y)
        self._draw(self._snapshot)
        byte_count = WIDTH * strip_height * 2
        self.lcd.show_region(
            0, self._next_y, WIDTH, strip_height,
            memoryview(self.canvas.buffer)[:byte_count],
        )
        self._next_y += strip_height
        return True

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
                if unit in ("G", "T"):
                    return "{:.1f}{}".format(amount, unit)
                return "{:.0f}{}".format(amount, unit)
            amount /= 1024
        return "0B"

    @staticmethod
    def _format_uptime(seconds):
        """将运行秒数格式化为天、小时和分钟。"""
        total_minutes = int(DashboardRenderer._number(seconds)) // 60
        days, remainder = divmod(total_minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}".format(days, hours, minutes)

    def _draw_bar(self, x, y, width, height, percent, color):
        """绘制百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        self.canvas.fill_rect(x, y, width, height, DARK)
        self.canvas.fill_rect(
            x + 1,
            y + 1,
            int((width - 2) * value / 100),
            height - 2,
            color,
        )

    def _draw_history(self, x, y, width, height, values, color, maximum=100):
        """将一组历史数值绘制为折线趋势图。"""
        if not values or len(values) < 2:
            return
        points = []
        count = len(values)
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (count - 1))
            ratio = max(0, min(1, self._number(value) / max(1, maximum)))
            points.append((point_x, y + height - 1 - int(ratio * (height - 1))))
        for index in range(1, len(points)):
            self.canvas.line(
                points[index - 1][0],
                points[index - 1][1],
                points[index][0],
                points[index][1],
                color,
            )

    def _draw_metric_card(self, y, title, percent, detail, history, color):
        """绘制 CPU、内存或磁盘的通用指标卡片。"""
        self.canvas.text(8, y, title, color, 2)
        self.canvas.text(94, y, "{}%".format(int(self._number(percent))), WHITE, 2)
        self.canvas.text(8, y + 22, detail, GRAY, 1)
        self._draw_bar(8, y + 34, 105, 10, percent, color)
        self._draw_history(126, y + 18, 105, 27, history, color)

    def _draw(self, snapshot):
        """绘制最新系统快照并将完整帧提交到 LCD。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        self.canvas.clear(BLACK)

        host = str(snapshot.get("host", "WAITING"))[:18]
        self.canvas.text(8, 8, host, WHITE, 2)
        status_color = GREEN if network.get("online") else RED
        self.canvas.fill_rect(219, 10, 12, 12, status_color)
        self.canvas.line(0, 34, WIDTH - 1, 34, GRAY)

        temperature = cpu.get("temperature_c")
        temperature_text = "--C" if temperature is None else "{}C".format(
            int(self._number(temperature))
        )
        self._draw_metric_card(
            43,
            "CPU",
            cpu.get("percent"),
            "TEMP " + temperature_text,
            cpu.get("history", ()),
            BLUE,
        )
        self._draw_metric_card(
            100,
            "RAM",
            memory.get("percent"),
            self._format_bytes(memory.get("used_bytes"))
            + "/"
            + self._format_bytes(memory.get("total_bytes")),
            memory.get("history", ()),
            GREEN,
        )
        self._draw_metric_card(
            157,
            "DISK",
            disk.get("percent"),
            self._format_bytes(disk.get("used_bytes"))
            + "/"
            + self._format_bytes(disk.get("total_bytes")),
            disk.get("history", ()),
            YELLOW,
        )

        self.canvas.line(0, 213, WIDTH - 1, 213, GRAY)
        self.canvas.text(8, 222, "NET", PURPLE, 2)
        self.canvas.text(
            8,
            245,
            "UP " + self._format_bytes(network.get("upload_bps")) + "/S",
            BLUE,
            1,
        )
        self.canvas.text(
            122,
            245,
            "DN " + self._format_bytes(network.get("download_bps")) + "/S",
            GREEN,
            1,
        )
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
        self.canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
        self.canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)

        self.canvas.line(0, 280, WIDTH - 1, 280, GRAY)
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        self.canvas.text(8, 292, clock, WHITE, 2)
        self.canvas.text(
            116,
            294,
            self._format_uptime(snapshot.get("uptime_seconds")),
            GRAY,
            1,
        )
