#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""实现紧凑型多磁盘横屏监控样式。"""


from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from style_plugins import register_style


SUCCESS = 0x6607
WARNING = 0xFD20
DANGER = 0xF9C7
CYAN = 0x06DB


class DiskV3Style:
    """按截图布局绘制顶部状态栏、侧边指标和十五块磁盘卡片。"""

    name = "diskv3"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    def __init__(self):
        """初始化磁盘告警边框的逐帧闪烁相位。"""
        self._alert_blink_phase = False

    def begin_frame(self):
        """在每个显示帧开始时切换磁盘告警边框相位。"""
        self._alert_blink_phase = not self._alert_blink_phase

    @staticmethod
    def create_dirty_regions():
        """创建各个独立面板对应的增量刷新区域。"""
        return [
            ("header", 2, 2, 316, 13),
            ("cpu", 2, 17, 70, 53),
            ("memory", 2, 72, 70, 52),
            ("network", 2, 126, 70, 54),
            ("gpu", 2, 182, 70, 56),
            ("summary", 75, 17, 243, 25),
            ("disk_row_0", 75, 44, 243, 37),
            ("disk_row_1", 75, 83, 243, 37),
            ("disk_row_2", 75, 122, 243, 37),
            ("disk_row_3", 75, 161, 243, 37),
            ("disk_row_4", 75, 200, 243, 38),
        ]

    @staticmethod
    def _number(value, default=0):
        """安全地把快照字段转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _usage_color(cls, percent):
        """按照磁盘占用率返回绿、黄、橙、红四级状态色。"""
        value = cls._number(percent)
        if value >= 85:
            return DANGER
        if value >= 70:
            return WARNING
        if value >= 40:
            return YELLOW
        return SUCCESS

    @classmethod
    def _format_capacity(cls, value):
        """把字节容量格式化为紧凑的 GB 或 TB 文本。"""
        amount = max(0, cls._number(value)) / (1024 ** 3)
        if amount >= 1024:
            return "{:.2f}T".format(amount / 1024)
        return "{:.1f}G".format(amount)

    @classmethod
    def _format_capacity_pair(cls, used_bytes, total_bytes):
        """格式化已用与总容量，并在单位相同时省略前一个单位。"""
        used = cls._format_capacity(used_bytes)
        total = cls._format_capacity(total_bytes)
        if used[-1:] == total[-1:]:
            used = used[:-1]
        return used + "/" + total

    @classmethod
    def _format_rate(cls, value):
        """把每秒字节数格式化为适合侧栏宽度的速率。"""
        amount = max(0, cls._number(value))
        units = ("B/s", "K/s", "M/s", "G/s")
        index = 0
        while amount >= 1000 and index < len(units) - 1:
            amount /= 1000
            index += 1
        return ("{:.0f}" if amount >= 10 else "{:.1f}").format(amount) + units[index]

    @classmethod
    def _format_uptime(cls, seconds):
        """把运行秒数格式化为天、小时和分钟。"""
        minutes = max(0, int(cls._number(seconds))) // 60
        days, minutes = divmod(minutes, 1440)
        hours, minutes = divmod(minutes, 60)
        return "{}d{}h{}m".format(days, hours, minutes)

    @classmethod
    def _ping_color(cls, ping_ms):
        """按照网络延迟返回绿色、黄色或红色状态色。"""
        if ping_ms is None:
            return DANGER
        value = max(0, cls._number(ping_ms))
        if value < 50:
            return SUCCESS
        if value < 100:
            return WARNING
        return DANGER

    def _health_display(self, health):
        """根据 SMART 健康等级返回边框、名称、状态和全红显示参数。"""
        level = int(self._number(health))
        if level >= 5:
            status = "FAILED" if self._alert_blink_phase else "WARN"
            return DANGER, DANGER, status, DANGER, self._alert_blink_phase
        if level >= 4:
            color = DANGER if self._alert_blink_phase else WARNING
            return color, color, "CRITICAL", color, False
        if level >= 3:
            color = WARNING if self._alert_blink_phase else GRAY
            return color, color, "WARNING", color, False
        if level >= 2:
            return CYAN, CYAN, "NOTICE", CYAN, False
        if level >= 1:
            return SUCCESS, SUCCESS, "HEALTHY", SUCCESS, False
        return GRAY, GRAY, "UNKNOWN", GRAY, False

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断完整坐标区域是否与当前条带画布相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    @staticmethod
    def _frame(canvas, x, y, width, height, color=GRAY):
        """绘制一个像素宽的矩形边框。"""
        canvas.line(x, y, x + width - 1, y, color)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, color)
        canvas.line(x, y, x, y + height - 1, color)
        canvas.line(x + width - 1, y, x + width - 1, y + height - 1, color)

    @classmethod
    def _bar(cls, canvas, x, y, width, height, percent, color):
        """绘制深色轨道和对应占用比例的实心进度条。"""
        value = max(0, min(100, cls._number(percent)))
        canvas.fill_rect(x, y, width, height, DARK)
        canvas.fill_rect(x, y, int(width * value / 100), height, color)

    @classmethod
    def _history(cls, canvas, x, y, width, height, values, color):
        """在侧栏中绘制资源使用率的紧凑历史折线。"""
        if not values or len(values) < 2:
            return
        previous = None
        for index, item in enumerate(values):
            point_x = x + int(index * (width - 1) / (len(values) - 1))
            ratio = max(0, min(100, cls._number(item))) / 100
            point_y = y + height - 1 - int(ratio * (height - 1))
            if previous is not None:
                canvas.line(previous[0], previous[1], point_x, point_y, color)
            previous = (point_x, point_y)

    def _draw_header(self, canvas, snapshot):
        """绘制 IP 地址、时间和运行时长状态栏。"""
        self._frame(canvas, 2, 2, 316, 13, DARK)
        ip_text = "IP " + str(
            snapshot.get("network", {}).get("ip") or "--"
        )
        while ip_text and 8 + canvas.text_width(ip_text) > 137:
            ip_text = ip_text[:-1]
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        canvas.text(8, 5, ip_text, WHITE)
        canvas.text(145, 5, clock, WHITE)
        uptime = "UP " + self._format_uptime(snapshot.get("uptime_seconds"))
        canvas.text(314 - canvas.text_width(uptime), 5, uptime, WHITE)

    def _draw_cpu(self, canvas, snapshot):
        """绘制 CPU 当前占用率和历史趋势。"""
        data = snapshot.get("cpu", {})
        percent = self._number(data.get("percent"))
        percent_color = self._usage_color(percent)
        self._frame(canvas, 2, 17, 70, 53, DARK)
        canvas.text(8, 22, "CPU", BLUE, 2)
        canvas.text(8, 39, "{:.1f}%".format(percent), percent_color, 2)
        self._history(canvas, 8, 57, 58, 10, data.get("history", ()), BLUE)

    def _draw_memory(self, canvas, snapshot):
        """绘制内存占用率、容量和水平进度条。"""
        data = snapshot.get("memory", {})
        percent = self._number(data.get("percent"))
        percent_color = self._usage_color(percent)
        self._frame(canvas, 2, 72, 70, 52, DARK)
        canvas.text(8, 77, "MEM", PURPLE, 2)
        canvas.text(8, 94, "{:.1f}%".format(percent), percent_color, 2)
        self._bar(canvas, 8, 110, 58, 5, percent, PURPLE)
        detail = self._format_capacity_pair(
            data.get("used_bytes"), data.get("total_bytes"),
        )
        canvas.text(8, 117, detail[:12], WHITE)

    def _draw_network(self, canvas, snapshot):
        """绘制网络上下行速率和延迟。"""
        data = snapshot.get("network", {})
        ping = data.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}ms".format(int(self._number(ping)))
        self._frame(canvas, 2, 126, 70, 54, DARK)
        canvas.text(8, 131, "NET", CYAN, 2)
        canvas.text(8, 148, "UP", CYAN)
        canvas.text(31, 148, self._format_rate(data.get("upload_bps")), WHITE)
        canvas.text(8, 159, "DN", CYAN)
        canvas.text(31, 159, self._format_rate(data.get("download_bps")), WHITE)
        canvas.text(8, 170, "PING", CYAN)
        canvas.text(40, 170, ping_text, self._ping_color(ping))

    def _draw_gpu(self, canvas, snapshot):
        """绘制 GPU 占用率和历史趋势，无数据时显示不可用。"""
        data = snapshot.get("gpu") or {}
        percent = self._number(data.get("percent"))
        self._frame(canvas, 2, 182, 70, 56, DARK)
        canvas.text(8, 187, "GPU", GREEN, 2)
        value = "N/A" if not data else "{:.1f}%".format(percent)
        canvas.text(8, 204, value, WHITE, 2)
        self._history(canvas, 8, 224, 58, 10, data.get("history", ()), GREEN)

    def _draw_summary(self, canvas, snapshot):
        """绘制磁盘总体占用率、容量和长进度条。"""
        data = snapshot.get("disk", {})
        percent = self._number(data.get("percent"))
        color = self._usage_color(percent)
        self._frame(canvas, 75, 17, 243, 25, DARK)
        canvas.text(82, 21, "DISK OVERALL", WHITE)
        percent_text = "{:.1f}%".format(percent)
        detail = self._format_capacity_pair(
            data.get("used_bytes"), data.get("total_bytes"),
        )
        percent_x = 312 - canvas.text_width(percent_text, 2)
        detail_x = 158
        while detail and detail_x + canvas.text_width(detail) > percent_x - 7:
            detail = detail[:-1]
        canvas.text(percent_x, 19, percent_text, color, 2)
        canvas.text(detail_x, 21, detail, WHITE)
        self._bar(canvas, 82, 35, 229, 4, percent, color)

    def _draw_disks(self, canvas, snapshot, selected_row=None):
        """按照三列五行网格绘制最多十五块物理磁盘。"""
        disks = snapshot.get("physical_disks") or snapshot.get("disks", ())
        for index, disk in enumerate(disks[:15]):
            column, row = index % 3, index // 3
            if selected_row is not None and row != selected_row:
                continue
            x, y = 75 + column * 81, 44 + row * 39
            percent = self._number(disk.get("percent"))
            color = self._usage_color(percent)
            health = int(self._number(disk.get("health")))
            frame_color, name_color, status, status_color, all_red = (
                self._health_display(health)
            )
            name = str(disk.get("name") or "D{}".format(index)).upper()
            if name.startswith("DISK"):
                name = "D" + name[4:]
            self._frame(canvas, x, y, 79, 37, frame_color)
            percent_text = "{:.1f}%".format(percent)
            name = name[:7]
            name_width = 67 - canvas.text_width(status)
            while name and canvas.text_width(name) > name_width:
                name = name[:-1]
            canvas.text(x + 4, y + 4, name or "D", DANGER if all_red else name_color)
            canvas.text(
                x + 75 - canvas.text_width(status), y + 4,
                status, DANGER if all_red else status_color,
            )
            canvas.text(
                x + 75 - canvas.text_width(percent_text), y + 13,
                percent_text, DANGER if all_red else color,
            )
            self._bar(
                canvas, x + 4, y + 21, 71, 4, percent,
                DANGER if all_red else color,
            )
            capacity = self._format_capacity_pair(
                disk.get("used_bytes"), disk.get("total_bytes"),
            )
            while capacity and canvas.text_width(capacity) > 71:
                capacity = capacity[:-1]
            canvas.text(x + 4, y + 28, capacity, DANGER if all_red else WHITE)

    def draw_visible(self, canvas, snapshot):
        """绘制与当前条带相交的全部完整界面区域。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        panels = (
            (2, 15, self._draw_header), (17, 70, self._draw_cpu),
            (72, 124, self._draw_memory), (126, 180, self._draw_network),
            (182, 238, self._draw_gpu), (17, 42, self._draw_summary),
        )
        for top, bottom, draw_method in panels:
            if self._visible(canvas, top, bottom):
                draw_method(canvas, snapshot)
        if self._visible(canvas, 44, 238):
            self._draw_disks(canvas, snapshot)

    def draw_dirty(self, canvas, key, snapshot):
        """清空并重绘指定的动态面板。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        methods = {
            "header": self._draw_header, "cpu": self._draw_cpu,
            "memory": self._draw_memory, "network": self._draw_network,
            "gpu": self._draw_gpu, "summary": self._draw_summary,
        }
        if key.startswith("disk_row_"):
            self._draw_disks(canvas, snapshot, int(key[-1]))
        else:
            methods[key](canvas, snapshot)


def create_diskv3_style():
    """创建顶部显示 IP 地址的紧凑型多磁盘横屏样式插件。"""
    return DiskV3Style()


register_style(DiskV3Style.name, create_diskv3_style)
