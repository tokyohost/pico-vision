"""实现项目原有 LCD 仪表盘的默认样式插件。"""

from config import (
    BLACK, BLUE, DARK, GRAY, GREEN, HEIGHT, PURPLE, RED, WHITE, WIDTH,
    YELLOW,
)
from style_plugins import register_style


class DefaultStyle:
    """封装默认仪表盘的布局、配色和数据格式化规则。"""

    name = "default"
    font_name = "native"

    @staticmethod
    def create_dirty_regions():
        """创建默认样式每帧需要刷新的动态区域。"""
        regions = [("status_light", 219, 10, 12, 12)]
        for name, y in (("cpu", 43), ("memory", 100), ("disk", 157)):
            regions.append((name + "_value", 94, y, 70, 14))
            regions.append((name + "_detail", 8, y + 22, 105, 22))
            regions.append((name + "_history", 126, y + 18, 105, 27))
        regions.append(("network_rate", 8, 245, 223, 8))
        regions.append(("network_status", 8, 261, 223, 8))
        regions.append(("footer", 8, 292, 223, 14))
        return regions

    @staticmethod
    def _number(value, default=0):
        """安全地将 JSON 数值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _format_bytes(cls, value):
        """将字节数格式化为适合屏幕显示的短文本。"""
        amount = cls._number(value)
        for unit in ("B", "K", "M", "G", "T"):
            if amount < 1024 or unit == "T":
                template = "{:.1f}{}" if unit in ("G", "T") else "{:.0f}{}"
                return template.format(amount, unit)
            amount /= 1024
        return "0B"

    @classmethod
    def _format_network_rate(cls, value, unit):
        """按字节或比特模式自动选择合适的网络速率量级。"""
        amount = max(0, cls._number(value))
        if unit == "Mbps":
            amount *= 8
            units = ("bps", "Kbps", "Mbps", "Gbps", "Tbps")
        else:
            units = ("B/S", "KB/S", "MB/S", "GB/S", "TB/S")
        unit_index = 0
        while amount >= 1000 and unit_index < len(units) - 1:
            amount /= 1000
            unit_index += 1
        if unit_index == 0 or amount >= 100:
            template = "{:.0f}{}"
        elif amount >= 10:
            template = "{:.1f}{}"
        else:
            template = "{:.2f}{}"
        return template.format(amount, units[unit_index])

    @classmethod
    def _format_uptime(cls, seconds):
        """将运行秒数格式化为天、小时和分钟。"""
        minutes = int(cls._number(seconds)) // 60
        days, remainder = divmod(minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}".format(days, hours, minutes)

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断纵向区域是否与当前画布视口相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    def _draw_bar(self, canvas, x, y, width, height, percent, color):
        """绘制百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x + 1, y + 1, int((width - 2) * value / 100), height - 2, color)

    def _draw_history(self, canvas, x, y, width, height, values, color):
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
                canvas.line(previous[0], previous[1], point[0], point[1], color)
            previous = point

    def _draw_metric(self, canvas, y, title, data, color, detail):
        """绘制单个 CPU、内存或磁盘指标区域。"""
        percent = data.get("percent")
        canvas.text(8, y, title, color, 2)
        canvas.text(94, y, "{}%".format(int(self._number(percent))), WHITE, 2)
        canvas.text(8, y + 22, detail, GRAY, 1)
        self._draw_bar(canvas, 8, y + 34, 105, 10, percent, color)
        self._draw_history(canvas, 126, y + 18, 105, 27, data.get("history", ()), color)

    def draw_dirty(self, canvas, key, snapshot):
        """清空并重绘默认样式的一个动态脏矩形。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        network_unit = snapshot.get("display", {}).get("network_unit", "MB")
        canvas.clear(BLACK)
        if key == "status_light":
            canvas.fill_rect(219, 10, 12, 12, GREEN if network.get("online") else RED)
            return
        if key == "network_rate":
            canvas.text(8, 245, "UP " + self._format_network_rate(network.get("upload_bps"), network_unit), BLUE, 1)
            canvas.text(122, 245, "DN " + self._format_network_rate(network.get("download_bps"), network_unit), GREEN, 1)
            return
        if key == "network_status":
            ping = network.get("ping_ms")
            ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
            canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
            canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)
            return
        if key == "footer":
            timestamp = str(snapshot.get("timestamp", ""))
            clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
            canvas.text(8, 292, clock, WHITE, 2)
            canvas.text(116, 294, self._format_uptime(snapshot.get("uptime_seconds")), GRAY, 1)
            return
        name, part = key.rsplit("_", 1)
        if name == "cpu":
            data, y, color = cpu, 43, BLUE
            temperature = data.get("temperature_c")
            detail = "TEMP " + ("--℃" if temperature is None else "{}℃".format(int(self._number(temperature))))
        elif name == "memory":
            data, y, color = memory, 100, GREEN
            detail = self._format_bytes(data.get("used_bytes")) + "/" + self._format_bytes(data.get("total_bytes"))
        else:
            data, y, color = disk, 157, YELLOW
            detail = self._format_bytes(data.get("used_bytes")) + "/" + self._format_bytes(data.get("total_bytes"))
        if part == "value":
            canvas.text(94, y, "{}%".format(int(self._number(data.get("percent")))), WHITE, 2)
        elif part == "detail":
            canvas.text(8, y + 22, detail, GRAY, 1)
            self._draw_bar(canvas, 8, y + 34, 105, 10, data.get("percent"), color)
        else:
            self._draw_history(canvas, 126, y + 18, 105, 27, data.get("history", ()), color)

    def draw_visible(self, canvas, snapshot):
        """绘制默认样式中与当前条带相交的全部内容。"""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        memory = snapshot.get("memory", {})
        disk = snapshot.get("disk", {})
        network = snapshot.get("network", {})
        network_unit = snapshot.get("display", {}).get("network_unit", "MB")
        canvas.clear(BLACK)
        if self._visible(canvas, 0, 35):
            canvas.text(8, 8, str(snapshot.get("host", "WAITING"))[:18], WHITE, 2)
            canvas.fill_rect(219, 10, 12, 12, GREEN if network.get("online") else RED)
            canvas.line(0, 34, WIDTH - 1, 34, GRAY)
        if self._visible(canvas, 43, 88):
            temperature = cpu.get("temperature_c")
            text = "--℃" if temperature is None else "{}℃".format(int(self._number(temperature)))
            self._draw_metric(canvas, 43, "CPU", cpu, BLUE, "TEMP " + text)
        if self._visible(canvas, 100, 145):
            detail = self._format_bytes(memory.get("used_bytes")) + "/" + self._format_bytes(memory.get("total_bytes"))
            self._draw_metric(canvas, 100, "RAM", memory, GREEN, detail)
        if self._visible(canvas, 157, 202):
            detail = self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes"))
            self._draw_metric(canvas, 157, "DISK", disk, YELLOW, detail)
        if self._visible(canvas, 213, 280):
            canvas.line(0, 213, WIDTH - 1, 213, GRAY)
            canvas.text(8, 222, "NET", PURPLE, 2)
            canvas.text(8, 245, "UP " + self._format_network_rate(network.get("upload_bps"), network_unit), BLUE, 1)
            canvas.text(122, 245, "DN " + self._format_network_rate(network.get("download_bps"), network_unit), GREEN, 1)
            ping = network.get("ping_ms")
            ping_text = "ERR" if ping is None else "{}MS".format(int(self._number(ping)))
            canvas.text(8, 261, "PING " + ping_text, PURPLE, 1)
            canvas.text(122, 261, str(network.get("ip", "0.0.0.0"))[:16], WHITE, 1)
        if self._visible(canvas, 280, HEIGHT):
            canvas.line(0, 280, WIDTH - 1, 280, GRAY)
            timestamp = str(snapshot.get("timestamp", ""))
            clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
            canvas.text(8, 292, clock, WHITE, 2)
            canvas.text(116, 294, self._format_uptime(snapshot.get("uptime_seconds")), GRAY, 1)


def create_default_style():
    """创建默认 LCD 样式插件。"""
    return DefaultStyle()


register_style(DefaultStyle.name, create_default_style)
