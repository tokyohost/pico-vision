"""实现参考监控大屏布局的横向 LCD 仪表盘样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, WHITE, YELLOW
from style_plugins import register_style


class HorizontalStyle:
    """封装三百二十乘二百四十横屏仪表盘的绘制规则。"""

    name = "horizontal"
    width = 320
    height = 240
    landscape = True

    @staticmethod
    def create_dirty_regions():
        """按独立数据面板创建横屏样式的动态刷新区域。"""
        return [
            ("cpu", 2, 2, 100, 69),
            ("memory", 2, 75, 100, 48),
            ("network", 2, 127, 100, 82),
            ("storage_summary", 106, 2, 212, 43),
            ("disk_row_0", 106, 49, 212, 48),
            ("disk_row_1", 106, 101, 212, 48),
            ("disk_row_2", 106, 153, 212, 48),
            ("footer", 2, 213, 316, 25),
        ]

    @staticmethod
    def _number(value, default=0):
        """安全地把快照值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _format_bytes(cls, value):
        """把字节数格式化为适合横屏卡片的容量文本。"""
        amount = max(0, cls._number(value))
        for unit in ("B", "K", "M", "G", "T"):
            if amount < 1024 or unit == "T":
                return ("{:.1f}{}" if unit in ("G", "T") else "{:.0f}{}").format(amount, unit)
            amount /= 1024
        return "0B"

    @classmethod
    def _format_disk_capacity(cls, used_bytes, total_bytes):
        """使用共享单位生成不超过八个字符的磁盘容量文本。"""
        used = max(0, cls._number(used_bytes))
        total = max(0, cls._number(total_bytes))
        units = ("B", "K", "M", "G", "T")
        unit_index = 0
        while total >= 1024 and unit_index < len(units) - 1:
            used /= 1024
            total /= 1024
            unit_index += 1

        def compact(value):
            """按当前容量量级输出最短且可辨识的数值。"""
            if value >= 10:
                return str(int(round(value)))
            return "{:.1f}".format(value)

        result = "{}/{}{}".format(
            compact(used), compact(total), units[unit_index]
        )
        if len(result) > 8 and unit_index < len(units) - 1:
            used /= 1024
            total /= 1024
            unit_index += 1
            result = "{}/{}{}".format(
                compact(used), compact(total), units[unit_index]
            )
        return result[:8]

    @classmethod
    def _format_rate(cls, value, unit):
        """按监控端配置格式化网络传输速率。"""
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
        """把运行秒数格式化为紧凑的天时分文本。"""
        minutes = int(cls._number(seconds)) // 60
        days, remainder = divmod(minutes, 1440)
        hours, minutes = divmod(remainder, 60)
        return "{}D {:02d}H {:02d}M".format(days, hours, minutes)

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断指定区域是否与当前绘制条带相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    @staticmethod
    def _frame(canvas, x, y, width, height, color):
        """绘制一像素矩形边框。"""
        canvas.line(x, y, x + width - 1, y, color)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, color)
        canvas.line(x, y, x, y + height - 1, color)
        canvas.line(x + width - 1, y, x + width - 1, y + height - 1, color)

    def _bar(self, canvas, x, y, width, height, percent, color):
        """绘制带边框的百分比进度条。"""
        value = max(0, min(100, self._number(percent)))
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x + 1, y + 1, int((width - 2) * value / 100), height - 2, color)
        self._frame(canvas, x, y, width, height, GRAY)

    def _history(self, canvas, x, y, width, height, values, color, percentage=False):
        """绘制含点阵背景的历史趋势折线。"""
        for grid_x in range(x, x + width, 12):
            for grid_y in range(y, y + height, 7):
                canvas.pixel(grid_x, grid_y, GRAY)
        if not values or len(values) < 2:
            return
        maximum = 100 if percentage else max(1, max(self._number(item) for item in values))
        previous = None
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (len(values) - 1))
            ratio = max(0, min(1, self._number(value) / maximum))
            point_y = y + height - 1 - int(ratio * (height - 1))
            if previous is not None:
                canvas.line(previous[0], previous[1], point_x, point_y, color)
            previous = (point_x, point_y)

    def _draw_cpu(self, canvas, snapshot):
        """绘制左上角 CPU 百分比、温度与趋势。"""
        cpu = snapshot.get("cpu", {})
        percent = int(self._number(cpu.get("percent")))
        temperature = cpu.get("temperature_c")
        temperature_text = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
        self._frame(canvas, 2, 2, 100, 69, GREEN)
        canvas.text(8, 7, "CPU", GREEN, 2)
        canvas.text(8, 27, "{}%".format(percent), GREEN, 3)
        canvas.text(66, 31, temperature_text, GREEN, 1)
        self._history(canvas, 8, 53, 88, 13, cpu.get("history", ()), GREEN, True)

    def _draw_memory(self, canvas, snapshot):
        """绘制左侧内存占用率与容量进度条。"""
        memory = snapshot.get("memory", {})
        percent = int(self._number(memory.get("percent")))
        self._frame(canvas, 2, 75, 100, 48, PURPLE)
        canvas.text(8, 80, "MEM", PURPLE, 1)
        canvas.text(8, 94, "{}%".format(percent), PURPLE, 2)
        self._bar(canvas, 49, 95, 47, 12, percent, PURPLE)
        detail = self._format_bytes(memory.get("used_bytes")) + "/" + self._format_bytes(memory.get("total_bytes"))
        canvas.text(8, 111, detail, WHITE, 1)

    def _draw_network(self, canvas, snapshot):
        """绘制左侧上下行速率、历史趋势和延迟。"""
        network = snapshot.get("network", {})
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        self._frame(canvas, 2, 127, 100, 82, BLUE)
        canvas.text(8, 132, "NETWORK", BLUE, 1)
        canvas.text(8, 145, "UP " + self._format_rate(network.get("upload_bps"), unit), WHITE, 1)
        self._history(canvas, 8, 157, 88, 13, network.get("upload_history", ()), BLUE)
        canvas.text(8, 174, "DN " + self._format_rate(network.get("download_bps"), unit), WHITE, 1)
        self._history(canvas, 8, 186, 88, 12, network.get("download_history", ()), BLUE)
        ping = network.get("ping_ms")
        canvas.text(8, 199, "PING " + ("ERR" if ping is None else "{}MS".format(int(self._number(ping)))), BLUE, 1)

    def _draw_storage_summary(self, canvas, snapshot):
        """绘制右上角磁盘总容量和总体占用率。"""
        disk = snapshot.get("disk", {})
        percent = int(self._number(disk.get("percent")))
        self._frame(canvas, 106, 2, 212, 43, YELLOW)
        canvas.text(112, 7, "STORAGE OVERALL", YELLOW, 1)
        capacity = self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes"))
        canvas.text(112, 20, capacity, WHITE, 1)
        canvas.text(280, 7, "{}%".format(percent), YELLOW, 2)
        self._bar(canvas, 112, 33, 198, 8, percent, YELLOW)

    def _draw_disk_cards(self, canvas, snapshot, selected_row=None):
        """按三列网格绘制指定行或全部物理磁盘卡片。"""
        disks = snapshot.get("disks", ())[:9]
        for index, disk in enumerate(disks):
            column, row = index % 3, index // 3
            if selected_row is not None and row != selected_row:
                continue
            x, y = 106 + column * 71, 49 + row * 52
            self._frame(canvas, x, y, 68, 48, YELLOW)
            name = str(disk.get("name", "DISK{}".format(index)))[:5]
            temperature = disk.get("temperature_c")
            temperature_text = "--C" if temperature is None else "{}C".format(int(self._number(temperature)))
            canvas.text(x + 4, y + 4, name, YELLOW, 1)
            canvas.text(x + 43, y + 4, temperature_text, WHITE, 1)
            capacity = self._format_disk_capacity(
                disk.get("used_bytes"), disk.get("total_bytes")
            )
            canvas.text(x + 3, y + 18, capacity[:8], WHITE, 1)
            percent = int(self._number(disk.get("percent")))
            canvas.text(x + 4, y + 32, "{}%".format(percent), YELLOW, 1)
            self._bar(canvas, x + 38, y + 34, 25, 8, percent, YELLOW)

    def _draw_footer(self, canvas, snapshot):
        """绘制横屏底部的时间、运行时长和功耗。"""
        self._frame(canvas, 2, 213, 316, 25, BLUE)
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        canvas.text(8, 221, clock, BLUE, 1)
        canvas.text(79, 221, "UPTIME " + self._format_uptime(snapshot.get("uptime_seconds")), WHITE, 1)
        watts = snapshot.get("power", {}).get("watts")
        power_text = "--W" if watts is None else "{:.0f}W".format(self._number(watts))
        canvas.text(267, 221, power_text, YELLOW, 1)

    def draw_visible(self, canvas, snapshot):
        """绘制与当前条带相交的横屏仪表盘内容。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if self._visible(canvas, 2, 71):
            self._draw_cpu(canvas, snapshot)
        if self._visible(canvas, 75, 123):
            self._draw_memory(canvas, snapshot)
        if self._visible(canvas, 127, 209):
            self._draw_network(canvas, snapshot)
        if self._visible(canvas, 2, 45):
            self._draw_storage_summary(canvas, snapshot)
        if self._visible(canvas, 49, 205):
            self._draw_disk_cards(canvas, snapshot)
        if self._visible(canvas, 213, 238):
            self._draw_footer(canvas, snapshot)

    def draw_dirty(self, canvas, key, snapshot):
        """仅重绘横屏样式中指定的动态数据面板。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "cpu":
            self._draw_cpu(canvas, snapshot)
        elif key == "memory":
            self._draw_memory(canvas, snapshot)
        elif key == "network":
            self._draw_network(canvas, snapshot)
        elif key == "storage_summary":
            self._draw_storage_summary(canvas, snapshot)
        elif key.startswith("disk_row_"):
            self._draw_disk_cards(canvas, snapshot, int(key[-1]))
        else:
            self._draw_footer(canvas, snapshot)


def create_horizontal_style():
    """创建横屏 LCD 仪表盘样式插件。"""
    return HorizontalStyle()


register_style(HorizontalStyle.name, create_horizontal_style)
