"""实现以磁盘容量为核心的高对比度 LCD 仪表盘样式。"""

from config import (
    BLACK, BLUE, DARK, GRAY, GREEN, HEIGHT, PURPLE, WHITE, WIDTH, YELLOW,
)
from style_plugins import register_style


class DiskStyle:
    """封装磁盘主视图的布局、格式化和增量绘制规则。"""

    name = "disk"
    font_name = "native"

    @staticmethod
    def create_dirty_regions():
        """创建磁盘样式每帧需要刷新的动态区域。"""
        return [
            ("disk_summary", 8, 25, 224, 38),
            ("cpu", 8, 88, 108, 47),
            ("memory", 124, 88, 108, 47),
            ("network_up", 8, 176, 224, 39),
            ("network_down", 8, 224, 224, 39),
            ("footer", 8, 286, 224, 25),
        ]

    @staticmethod
    def _number(value, default=0):
        """安全地将快照中的数值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _format_bytes(cls, value):
        """将字节数格式化为紧凑的容量文本。"""
        amount = max(0, cls._number(value))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if amount < 1024 or unit == "TB":
                return ("{:.1f}{}" if unit in ("GB", "TB") else "{:.0f}{}").format(amount, unit)
            amount /= 1024
        return "0B"

    @classmethod
    def _format_rate(cls, value, unit):
        """按照用户设置格式化网络传输速率。"""
        amount = max(0, cls._number(value))
        if unit == "Mbps":
            amount *= 8
            units = ("BPS", "KBPS", "MBPS", "GBPS")
        else:
            units = ("B/S", "KB/S", "MB/S", "GB/S")
        index = 0
        while amount >= 1000 and index < len(units) - 1:
            amount /= 1000
            index += 1
        return ("{:.0f}{}" if amount >= 100 else "{:.1f}{}").format(amount, units[index])

    @classmethod
    def _format_uptime(cls, seconds):
        """将运行秒数格式化为短运行时长。"""
        minutes = int(cls._number(seconds)) // 60
        days, remainder = divmod(minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D{:02d}H{:02d}M".format(days, hours, minutes)

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断纵向区域是否与当前画布视口相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    def _draw_frame(self, canvas, x, y, width, height, color):
        """绘制一像素宽的矩形边框。"""
        canvas.line(x, y, x + width - 1, y, color)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, color)
        canvas.line(x, y, x, y + height - 1, color)
        canvas.line(x + width - 1, y, x + width - 1, y + height - 1, color)

    def _draw_bar(self, canvas, x, y, width, height, percent, color):
        """绘制带亮色边框的百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x + 1, y + 1, int((width - 2) * value / 100), height - 2, color)
        self._draw_frame(canvas, x, y, width, height, color)

    def _draw_history(self, canvas, x, y, width, height, values, color):
        """绘制带点阵网格的历史折线。"""
        for grid_x in range(x, x + width, 16):
            for grid_y in range(y, y + height, 8):
                canvas.pixel(grid_x, grid_y, GRAY)
        if not values or len(values) < 2:
            return
        previous = None
        count = len(values)
        maximum = max(1, max(self._number(value) for value in values))
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (count - 1))
            ratio = max(0, min(1, self._number(value) / maximum))
            point_y = y + height - 1 - int(ratio * (height - 1))
            if previous is not None:
                canvas.line(previous[0], previous[1], point_x, point_y, color)
            previous = (point_x, point_y)

    def _draw_disk_summary(self, canvas, snapshot):
        """绘制磁盘容量、占用率和总进度条。"""
        disk = snapshot.get("disk", {})
        percent = int(self._number(disk.get("percent")))
        capacity = self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes"))
        canvas.text(8, 25, capacity, WHITE, 1)
        canvas.text(184, 23, "{}%".format(percent), YELLOW, 2)
        self._draw_bar(canvas, 8, 43, 224, 20, percent, YELLOW)

    def _draw_metric_card(self, canvas, x, title, data, color, detail):
        """绘制 CPU 或内存的紧凑指标卡片内容。"""
        percent = int(self._number(data.get("percent")))
        canvas.text(x, 88, title, color, 1)
        canvas.text(x, 101, "{}%".format(percent), color, 2)
        canvas.text(x + 48, 105, detail[:10], WHITE, 1)
        self._draw_bar(canvas, x, 125, 108, 10, percent, color)

    def _draw_network_line(self, canvas, snapshot, upload):
        """绘制上传或下载速率及其历史折线。"""
        network = snapshot.get("network", {})
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        if upload:
            y, title, color = 176, "UP", BLUE
            rate_key, history_key = "upload_bps", "upload_history"
        else:
            y, title, color = 224, "DOWN", GREEN
            rate_key, history_key = "download_bps", "download_history"
        canvas.text(8, y, title, color, 1)
        canvas.text(58, y, self._format_rate(network.get(rate_key), unit), WHITE, 1)
        self._draw_history(canvas, 8, y + 12, 224, 27, network.get(history_key, ()), color)

    def _draw_footer(self, canvas, snapshot):
        """绘制时钟、运行时长、延迟和联网状态。"""
        network = snapshot.get("network", {})
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
        canvas.text(8, 286, clock, BLUE, 1)
        canvas.text(88, 286, self._format_uptime(snapshot.get("uptime_seconds")), WHITE, 1)
        canvas.text(184, 286, ping_text, GREEN if network.get("online") else PURPLE, 1)
        canvas.text(8, 301, str(snapshot.get("host", "WAITING"))[:18], GRAY, 1)

    def draw_dirty(self, canvas, key, snapshot):
        """清空并重绘磁盘样式的一个动态区域。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "disk_summary":
            self._draw_disk_summary(canvas, snapshot)
        elif key == "cpu":
            cpu = snapshot.get("cpu", {})
            temperature = cpu.get("temperature_c")
            detail = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
            self._draw_metric_card(canvas, 8, "CPU", cpu, GREEN, detail)
        elif key == "memory":
            memory = snapshot.get("memory", {})
            self._draw_metric_card(canvas, 124, "MEM", memory, PURPLE, self._format_bytes(memory.get("used_bytes")))
        elif key == "network_up":
            self._draw_network_line(canvas, snapshot, True)
        elif key == "network_down":
            self._draw_network_line(canvas, snapshot, False)
        else:
            self._draw_footer(canvas, snapshot)

    def draw_visible(self, canvas, snapshot):
        """绘制磁盘样式中与当前条带相交的全部内容。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if self._visible(canvas, 0, 72):
            canvas.text(8, 5, "STORAGE OVERALL", YELLOW, 2)
            self._draw_disk_summary(canvas, snapshot)
            self._draw_frame(canvas, 2, 1, 236, 70, YELLOW)
        if self._visible(canvas, 78, 145):
            cpu = snapshot.get("cpu", {})
            memory = snapshot.get("memory", {})
            temperature = cpu.get("temperature_c")
            cpu_detail = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
            self._draw_frame(canvas, 2, 78, 116, 67, GREEN)
            self._draw_frame(canvas, 122, 78, 116, 67, PURPLE)
            self._draw_metric_card(canvas, 8, "CPU", cpu, GREEN, cpu_detail)
            self._draw_metric_card(canvas, 124, "MEM", memory, PURPLE, self._format_bytes(memory.get("used_bytes")))
        if self._visible(canvas, 151, 270):
            canvas.text(8, 154, "NETWORK", BLUE, 2)
            self._draw_frame(canvas, 2, 151, 236, 119, BLUE)
            self._draw_network_line(canvas, snapshot, True)
            self._draw_network_line(canvas, snapshot, False)
        if self._visible(canvas, 277, HEIGHT):
            self._draw_frame(canvas, 2, 277, 236, 41, BLUE)
            self._draw_footer(canvas, snapshot)


def create_disk_style():
    """创建磁盘主视图 LCD 样式插件。"""
    return DiskStyle()


register_style(DiskStyle.name, create_disk_style)
