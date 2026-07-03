"""实现以磁盘统计为重点的横向 LCD 仪表盘样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from style_plugins import register_style


# Element UI 经典状态色转换后的 RGB565 色值。
ELEMENT_SUCCESS = 0x6607
ELEMENT_WARNING = 0xE507
ELEMENT_DANGER = 0xF36D
NETWORK_RATE_MAX_CHARS = 8


class HorizontalDisk4xStyle:
    """封装每行双磁盘、最多显示四块磁盘的横向仪表盘绘制规则。"""

    name = "horizontal_disk4x"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    def __init__(self):
        """初始化磁盘健康告警的逐帧闪烁相位。"""
        self._health_blink_phase = False

    def begin_frame(self):
        """在新显示帧开始时切换一次磁盘健康告警相位。"""
        self._health_blink_phase = not self._health_blink_phase

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
            ("network_details", 106, 153, 212, 56),
            ("footer", 2, 213, 316, 25),
        ]

    @classmethod
    def select_dirty_regions(cls, previous, current):
        """根据相邻快照差异仅返回实际变化的横屏面板。"""
        regions = cls.create_dirty_regions()
        selected = []
        region_map = {region[0]: region for region in regions}
        if previous.get("cpu") != current.get("cpu"):
            selected.append(region_map["cpu"])
        if previous.get("memory") != current.get("memory"):
            selected.append(region_map["memory"])
        previous_network = (
            previous.get("network"),
            previous.get("display", {}).get("network_unit"),
        )
        current_network = (
            current.get("network"),
            current.get("display", {}).get("network_unit"),
        )
        if previous_network != current_network:
            selected.append(region_map["network"])
            selected.append(region_map["network_details"])
        if (
            previous.get("gpu") != current.get("gpu")
            and region_map["network_details"] not in selected
        ):
            selected.append(region_map["network_details"])
        if previous.get("disk") != current.get("disk"):
            selected.append(region_map["storage_summary"])
        previous_disks = previous.get("physical_disks") or previous.get("disks", ())
        current_disks = current.get("physical_disks") or current.get("disks", ())
        for row in range(2):
            start = row * 2
            current_row = current_disks[start:start + 2]
            has_health_alarm = any(cls._number(disk.get("health")) >= 3 for disk in current_row)
            if previous_disks[start:start + 2] != current_row or has_health_alarm:
                selected.append(region_map["disk_row_{}".format(row)])
        previous_footer = (
            previous.get("timestamp"), previous.get("uptime_seconds"),
            previous.get("power"),
        )
        current_footer = (
            current.get("timestamp"), current.get("uptime_seconds"),
            current.get("power"),
        )
        if previous_footer != current_footer:
            selected.append(region_map["footer"])
        return selected

    @staticmethod
    def _number(value, default=0):
        """安全地把快照值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _usage_color(cls, percent):
        """按照 Element UI 状态色返回资源占用率对应颜色。"""
        value = max(0, min(100, cls._number(percent)))
        if value < 50:
            return ELEMENT_SUCCESS
        if value < 80:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

    @classmethod
    def _disk_usage_color(cls, percent):
        """按照磁盘占用率分级返回状态颜色，九成及以上标记为危险。"""
        value = max(0, min(100, cls._number(percent)))
        if value < 50:
            return ELEMENT_SUCCESS
        if value < 90:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

    def _health_display(self, health, usage_color):
        """根据磁盘健康等级和当前帧相位返回告警绘制参数。"""
        level = int(self._number(health))
        if level >= 5:
            return RED, RED, self._health_blink_phase, not self._health_blink_phase
        if level >= 4:
            color = RED if self._health_blink_phase else YELLOW
            return color, color, False, False
        if level >= 3:
            color = YELLOW if self._health_blink_phase else GRAY
            return color, color, False, False
        return usage_color, usage_color, False, False

    @classmethod
    def _ping_color(cls, ping_ms):
        """按照网络延迟分级返回 Element UI 状态颜色。"""
        if ping_ms is None:
            return ELEMENT_DANGER
        value = max(0, cls._number(ping_ms))
        if value < 50:
            return ELEMENT_SUCCESS
        if value < 100:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

    @classmethod
    def _temperature_color(cls, temperature_c):
        """按照摄氏温度分级返回状态颜色，无数据时返回灰色。"""
        if temperature_c is None:
            return GRAY
        value = cls._number(temperature_c)
        if value < 50:
            return ELEMENT_SUCCESS
        if value < 70:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

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
        """按监控端配置生成不超过八个字符的网络速率。"""
        amount = max(0, cls._number(value))
        if unit == "Mbps":
            amount *= 8
            units = ("BPS", "KBPS", "MBPS", "GBPS")
        else:
            units = ("B/s", "KB/s", "MB/s", "GB/s")
        index = 0
        while amount >= 1000 and index < len(units) - 1:
            amount /= 1000
            index += 1
        while True:
            # 临近一千时提前提升单位，避免四位整数挤出边框。
            if amount >= 999.5 and index < len(units) - 1:
                amount /= 1000
                index += 1
                continue
            number = "{:.1f}".format(amount) if amount < 100 else str(int(round(amount)))
            result = number + units[index]
            if len(result) <= NETWORK_RATE_MAX_CHARS:
                return result
            if index < len(units) - 1:
                amount /= 1000
                index += 1
                continue
            available = NETWORK_RATE_MAX_CHARS - len(units[index])
            return (">" + "9" * max(0, available - 1) + units[index])[:NETWORK_RATE_MAX_CHARS]

    @classmethod
    def _format_disk_rate(cls, value):
        """把磁盘每秒字节数压缩为适合卡片显示的短速率文本。"""
        amount = max(0, cls._number(value))
        units = ("B", "K", "M", "G", "T")
        unit_index = 0
        while amount >= 1000 and unit_index < len(units) - 1:
            amount /= 1000
            unit_index += 1
        if amount >= 100:
            number = str(int(round(amount)))
        elif amount >= 10:
            number = "{:.1f}".format(amount).rstrip("0").rstrip(".")
        else:
            number = "{:.1f}".format(amount)
        return (number + units[unit_index])[:5]

    @classmethod
    def _format_link_speed(cls, value):
        """把网口协商速率格式化为紧凑的 Mbps 或 Gbps 文本。"""
        speed = max(0, cls._number(value))
        if speed <= 0:
            return "--Mbps"
        if speed >= 1000:
            gigabits = speed / 1000
            # MicroPython 的浮点对象不保证实现 is_integer，使用整数比较保持兼容。
            number = (
                str(int(gigabits))
                if gigabits == int(gigabits)
                else "{:.1f}".format(gigabits)
            )
            return number + "Gbps"
        return "{}Mbps".format(int(speed))

    @classmethod
    def _format_uptime(cls, seconds):
        """把运行秒数格式化为天数与时分秒文本。"""
        total_seconds = max(0, int(cls._number(seconds)))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}:{:02d}".format(
            days, hours, minutes, seconds
        )

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

    def _history(
        self, canvas, x, y, width, height, values, color,
        percentage=False, filled=False, color_by_value=False,
    ):
        """绘制历史趋势图，并可按照每个采样值保留独立的状态颜色。"""
        for grid_x in range(x, x + width, 12):
            for grid_y in range(y, y + height, 7):
                canvas.pixel(grid_x, grid_y, GRAY)
        if not values or len(values) < 2:
            return
        maximum = 100 if percentage else max(1, max(self._number(item) for item in values))
        points = []
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (len(values) - 1))
            numeric_value = self._number(value)
            ratio = max(0, min(1, numeric_value / maximum))
            point_y = y + height - 1 - int(ratio * (height - 1))
            points.append((point_x, point_y, numeric_value))
        if color_by_value:
            self._draw_value_colored_history(
                canvas, y, height, points, filled
            )
            return
        plain_points = [(point[0], point[1]) for point in points]
        native_filled = False
        if filled:
            native_filled = self._fill_history_area(
                canvas, x, y, width, height, plain_points, color
            )
        if native_filled:
            return
        previous = plain_points[0]
        for point in plain_points[1:]:
            canvas.line(previous[0], previous[1], point[0], point[1], color)
            previous = point

    def _draw_value_colored_history(self, canvas, y, height, points, filled):
        """按插值后的历史采样值逐列绘制颜色条带，使峰值颜色留在历史图中。"""
        bottom = y + height - 1
        previous = points[0]
        for point in points[1:]:
            span = max(1, point[0] - previous[0])
            for draw_x in range(previous[0], point[0] + 1):
                offset = draw_x - previous[0]
                draw_y = previous[1] + int(
                    (point[1] - previous[1]) * offset / span
                )
                value = previous[2] + (
                    (point[2] - previous[2]) * offset / span
                )
                sample_color = self._usage_color(value)
                if filled:
                    canvas.line(draw_x, draw_y, draw_x, bottom, sample_color)
                else:
                    canvas.pixel(draw_x, draw_y, sample_color)
            previous = point

    @staticmethod
    def _fill_history_area(canvas, x, y, width, height, points, color):
        """优先原生填充趋势图，并为旧固件选择调用次数较少的扫描方向。"""
        bottom = y + height - 1
        polygon = list(points)
        polygon.append((points[-1][0], bottom))
        polygon.append((points[0][0], bottom))
        if canvas.fill_polygon(polygon, color):
            return True
        top_by_x = [bottom] * width
        previous = points[0]
        for point in points[1:]:
            span = max(1, point[0] - previous[0])
            start = max(x, previous[0])
            end = min(x + width - 1, point[0])
            for fill_x in range(start, end + 1):
                offset = fill_x - previous[0]
                top_by_x[fill_x - x] = previous[1] + int(
                    (point[1] - previous[1]) * offset / span
                )
            previous = point
        scanline_runs = []
        for fill_y in range(y, bottom + 1):
            run_start = None
            for offset, top in enumerate(top_by_x):
                if top <= fill_y:
                    if run_start is None:
                        run_start = x + offset
                elif run_start is not None:
                    scanline_runs.append(
                        (run_start, fill_y, x + offset - 1, fill_y)
                    )
                    run_start = None
            if run_start is not None:
                scanline_runs.append(
                    (run_start, fill_y, x + width - 1, fill_y)
                )
        if len(scanline_runs) < width:
            for start_x, start_y, end_x, end_y in scanline_runs:
                canvas.line(start_x, start_y, end_x, end_y, color)
        else:
            for offset, top in enumerate(top_by_x):
                canvas.line(x + offset, top, x + offset, bottom, color)
        return False

    def _draw_cpu(self, canvas, snapshot):
        """绘制左上角 CPU 百分比、温度与趋势。"""
        cpu = snapshot.get("cpu", {})
        percent = int(self._number(cpu.get("percent")))
        usage_color = self._usage_color(percent)
        temperature = cpu.get("temperature_c")
        temperature_text = "--℃" if temperature is None else "{}℃".format(int(self._number(temperature)))
        self._frame(canvas, 2, 2, 100, 69, GREEN)
        canvas.text(8, 7, "CPU", GREEN, 1)
        canvas.text(
            8, 19, temperature_text,
            self._temperature_color(temperature), 1,
        )
        percent_text = "{}%".format(percent)
        canvas.text(
            100 - len(percent_text) * 12, 10,
            percent_text, usage_color, 2,
        )
        self._history(
            canvas, 8, 31, 88, 35,
            cpu.get("history", ()), usage_color,
            percentage=True, filled=True, color_by_value=True,
        )

    def _draw_memory(self, canvas, snapshot):
        """绘制左侧内存占用率与容量进度条。"""
        memory = snapshot.get("memory", {})
        percent = int(self._number(memory.get("percent")))
        usage_color = self._usage_color(percent)
        self._frame(canvas, 2, 75, 100, 48, PURPLE)
        canvas.text(8, 80, "MEM", PURPLE, 1)
        canvas.text(8, 94, "{}%".format(percent), usage_color, 2)
        self._bar(canvas, 49, 95, 47, 12, percent, usage_color)
        used_text = self._format_bytes(memory.get("used_bytes"))
        total_text = self._format_bytes(memory.get("total_bytes"))
        if used_text[-1:] == total_text[-1:]:
            used_text = used_text[:-1]
        detail = used_text + "/" + total_text
        canvas.text(8, 111, detail, WHITE, 1)

    def _draw_network(self, canvas, snapshot):
        """绘制左侧上下行速率、历史趋势和标题栏延迟。"""
        network = snapshot.get("network", {})
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        self._frame(canvas, 2, 127, 100, 82, BLUE)
        canvas.text(8, 132, "NET", BLUE, 1)
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "P{}ms".format(
            int(self._number(ping))
        )
        canvas.text(
            96 - len(ping_text) * 8, 132,
            ping_text, self._ping_color(ping), 1,
        )
        canvas.text(8, 143, "↑UP", WHITE, 1)
        canvas.text(
            32, 143,
            self._format_rate(network.get("upload_bps"), unit), BLUE, 1,
        )
        self._history(
            canvas, 8, 152, 88, 19,
            network.get("upload_history", ()), BLUE, filled=True,
        )
        canvas.text(8, 174, "↓DN", WHITE, 1)
        canvas.text(
            32, 174,
            self._format_rate(network.get("download_bps"), unit), GREEN, 1,
        )
        self._history(
            canvas, 8, 183, 88, 22,
            network.get("download_history", ()), GREEN, filled=True,
        )

    def _draw_storage_summary(self, canvas, snapshot):
        """绘制右上角磁盘总容量和总体占用率。"""
        disk = snapshot.get("disk", {})
        percent = int(self._number(disk.get("percent")))
        usage_color = self._disk_usage_color(percent)
        self._frame(canvas, 106, 2, 212, 43, YELLOW)
        canvas.text(112, 7, "DISK OVERALL", YELLOW, 1)
        capacity = self._format_bytes(disk.get("used_bytes")) + "/" + self._format_bytes(disk.get("total_bytes"))
        canvas.text(112, 20, capacity, WHITE, 1)
        canvas.text(280, 7, "{}%".format(percent), usage_color, 2)
        self._bar(canvas, 112, 33, 198, 8, percent, usage_color)

    def _draw_disk_cards(self, canvas, snapshot, selected_row=None):
        """按每行两张卡片绘制最多四块物理磁盘及其实时读写趋势。"""
        # 优先使用主机端明确提供的物理磁盘统计，并兼容旧版 disks 字段。
        disks = snapshot.get("physical_disks") or snapshot.get("disks", ())
        disks = disks[:4]
        for index, disk in enumerate(disks):
            column, row = index % 2, index // 2
            if selected_row is not None and row != selected_row:
                continue
            x, y = 106 + column * 106, 49 + row * 52
            percent = int(self._number(disk.get("percent")))
            usage_color = self._disk_usage_color(percent)
            frame_color, name_color, all_red, show_warning = self._health_display(
                disk.get("health", 0), usage_color
            )
            self._frame(canvas, x, y, 102, 48, frame_color)
            name = str(
                disk.get("name") or "DISK{}".format(index)
            ).strip().upper()
            if show_warning:
                name = "WARN"
            temperature = disk.get("temperature_c")
            temperature_text = "--℃" if temperature is None else "{}℃".format(int(self._number(temperature)))
            canvas.text(x + 3, y + 4, name, RED if all_red else name_color, 1)
            canvas.text(
                x + 99 - canvas.text_width(temperature_text), y + 4, temperature_text,
                RED if all_red else self._temperature_color(temperature), 1,
            )
            capacity = self._format_disk_capacity(
                disk.get("used_bytes"), disk.get("total_bytes")
            )
            canvas.text(x + 3, y + 15, capacity[:8], RED if all_red else WHITE, 1)
            percent_text = "{}%".format(percent)
            canvas.text(
                x + 99 - canvas.text_width(percent_text), y + 15,
                percent_text, RED if all_red else usage_color, 1,
            )
            read_text = "R" + self._format_disk_rate(disk.get("read_bps"))
            write_text = "W" + self._format_disk_rate(disk.get("write_bps"))
            canvas.text(x + 3, y + 27, read_text, RED if all_red else GREEN, 1)
            canvas.text(x + 3, y + 38, write_text, RED if all_red else YELLOW, 1)
            self._history(
                canvas, x + 42, y + 27, 57, 8,
                disk.get("read_history", ()), RED if all_red else GREEN, filled=True,
            )
            self._history(
                canvas, x + 42, y + 38, 57, 7,
                disk.get("write_history", ()), RED if all_red else YELLOW, filled=True,
            )

    def _draw_network_details(self, canvas, snapshot):
        """分栏绘制网络详情以及 GPU 使用率和实心历史折线图。"""
        network = snapshot.get("network", {})
        self._frame(canvas, 106, 153, 212, 56, BLUE)
        canvas.line(211, 154, 211, 207, BLUE)
        canvas.text(110, 157, "IP", BLUE, 1)
        canvas.text(126, 157, str(network.get("ip") or "0.0.0.0")[:15], WHITE, 1)
        canvas.text(110, 169, "LINK", BLUE, 1)
        canvas.text(
            142, 169,
            self._format_link_speed(network.get("link_speed_mbps")), WHITE, 1,
        )
        canvas.text(110, 181, "↑", BLUE, 1)
        canvas.text(
            122, 181,
            self._format_bytes(network.get("transmit_bytes")), WHITE, 1,
        )
        canvas.text(110, 193, "↓", GREEN, 1)
        canvas.text(
            122, 193,
            self._format_bytes(network.get("receive_bytes")), WHITE, 1,
        )
        gpu = snapshot.get("gpu") or {}
        gpu_percent = gpu.get("percent")
        if gpu_percent is not None:
            gpu_text = "{}%".format(int(self._number(gpu_percent)))
            canvas.text(216, 157, "GPU", PURPLE, 1)
            canvas.text(
                312 - canvas.text_width(gpu_text), 158,
                gpu_text, self._usage_color(gpu_percent), 1,
            )
            self._history(
                canvas, 216, 170, 96, 34,
                gpu.get("history", ()), self._usage_color(gpu_percent),
                percentage=True, filled=True, color_by_value=True,
            )

    def _draw_footer(self, canvas, snapshot):
        """绘制横屏底部的时间、运行时长和功耗。"""
        self._frame(canvas, 2, 213, 316, 25, BLUE)
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        canvas.text(8, 221, clock, BLUE, 1)
        canvas.line(77, 217, 77, 233, BLUE)
        canvas.text(85, 221, "UPTIME", BLUE, 1)
        uptime_text = self._format_uptime(snapshot.get("uptime_seconds"))
        canvas.text(
            231 - canvas.text_width(uptime_text), 221,
            uptime_text, WHITE, 1,
        )
        canvas.line(237, 217, 237, 233, BLUE)
        watts = snapshot.get("power", {}).get("watts")
        power_text = "--W" if watts is None else "{:.0f}W".format(self._number(watts))
        canvas.text(245, 221, "PWR", BLUE, 1)
        canvas.text(
            312 - canvas.text_width(power_text), 221,
            power_text, YELLOW, 1,
        )

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
        if self._visible(canvas, 49, 149):
            self._draw_disk_cards(canvas, snapshot)
        if self._visible(canvas, 153, 209):
            self._draw_network_details(canvas, snapshot)
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
        elif key == "network_details":
            self._draw_network_details(canvas, snapshot)
        else:
            self._draw_footer(canvas, snapshot)


def create_horizontal_disk4x_style():
    """创建每行双磁盘、最多四块磁盘的横向 LCD 样式插件。"""
    return HorizontalDisk4xStyle()


register_style(HorizontalDisk4xStyle.name, create_horizontal_disk4x_style)
