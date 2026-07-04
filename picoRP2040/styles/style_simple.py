#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""实现信息紧凑、磁盘健康优先的横屏 LCD 仪表盘样式。"""


from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from styles.style_horizontal_disk import (
    ELEMENT_DANGER, ELEMENT_SUCCESS, ELEMENT_WARNING, HorizontalDiskStyle,
)
from styles.style_plugins import register_style


class SimpleStyle(HorizontalDiskStyle):
    """绘制最多三块磁盘并使用渐变面积折线图的简洁横屏样式。"""

    name = "simple"
    font_name = "screen_2inch_compact"

    @staticmethod
    def create_dirty_regions():
        """返回简洁样式中可独立刷新的数据区域。"""
        return [
            ("cpu", 2, 2, 100, 50),
            ("memory", 2, 55, 100, 43),
            ("gpu", 2, 101, 100, 43),
            ("network", 2, 147, 100, 66),
            ("storage_summary", 106, 2, 212, 43),
            ("disk_row_0", 106, 48, 212, 52),
            ("disk_row_1", 106, 103, 212, 52),
            ("disk_row_2", 106, 158, 212, 52),
            ("footer", 2, 216, 316, 22),
        ]

    @classmethod
    def _selected_disks(cls, snapshot):
        """按健康等级由差到好稳定排序，并返回最多三块物理磁盘。"""
        disks = snapshot.get("physical_disks") or snapshot.get("disks", ())
        indexed_disks = list(enumerate(disks))
        indexed_disks.sort(
            key=lambda item: (-cls._number(item[1].get("health")), item[0])
        )
        return [item[1] for item in indexed_disks[:3]]

    @classmethod
    def _health_text_color(cls, health):
        """按照 Element 状态色返回 H0 至 H5 健康等级的文字颜色。"""
        level = max(0, min(5, int(cls._number(health))))
        colors = (
            GRAY, ELEMENT_SUCCESS, BLUE,
            ELEMENT_WARNING, ELEMENT_DANGER, RED,
        )
        return colors[level]

    @classmethod
    def select_dirty_regions(cls, previous, current):
        """比较相邻快照并返回实际发生变化或需要闪烁的区域。"""
        regions = {region[0]: region for region in cls.create_dirty_regions()}
        selected = []
        for key in ("cpu", "memory", "gpu", "network", "disk"):
            if previous.get(key) != current.get(key):
                region_key = "storage_summary" if key == "disk" else key
                selected.append(regions[region_key])
        old_disks = cls._selected_disks(previous)
        new_disks = cls._selected_disks(current)
        for index in range(3):
            old_disk = old_disks[index:index + 1]
            new_disk = new_disks[index:index + 1]
            has_alarm = bool(new_disk and cls._number(new_disk[0].get("health")) >= 3)
            if old_disk != new_disk or has_alarm:
                selected.append(regions["disk_row_{}".format(index)])
        old_footer = (previous.get("timestamp"), previous.get("uptime_seconds"))
        new_footer = (current.get("timestamp"), current.get("uptime_seconds"))
        if old_footer != new_footer:
            selected.append(regions["footer"])
        return selected

    @staticmethod
    def _blend_color(background, foreground, amount):
        """按给定比例混合两个 RGB565 颜色。"""
        ratio = max(0, min(255, int(amount)))
        inverse = 255 - ratio
        red = (((background >> 11) & 0x1F) * inverse + ((foreground >> 11) & 0x1F) * ratio) // 255
        green = (((background >> 5) & 0x3F) * inverse + ((foreground >> 5) & 0x3F) * ratio) // 255
        blue = ((background & 0x1F) * inverse + (foreground & 0x1F) * ratio) // 255
        return (red << 11) | (green << 5) | blue

    def _gradient_history(self, canvas, x, y, width, height, values, color, percentage=False):
        """使用少量竖线色带绘制由折线向底部变暗的实心渐变面积图。"""
        if not values or len(values) < 2:
            return
        maximum = 100 if percentage else max(1, max(self._number(value) for value in values))
        # 颜色只在每张图开始时计算一次，避免逐像素混色拖慢 RP2040。
        gradient_colors = (
            self._blend_color(BLACK, color, 195),
            self._blend_color(BLACK, color, 110),
            self._blend_color(BLACK, color, 40),
        )
        points = []
        for index, value in enumerate(values):
            point_x = x + int(index * (width - 1) / (len(values) - 1))
            ratio = max(0, min(1, self._number(value) / maximum))
            points.append((point_x, y + height - 1 - int(ratio * (height - 1))))
        bottom = y + height - 1
        segment_index = 1
        # 全图统一每三个横向像素采样一次，避免每段折线重复填充边界列。
        for draw_x in range(x, x + width, 3):
            while segment_index < len(points) - 1 and draw_x > points[segment_index][0]:
                segment_index += 1
            previous = points[segment_index - 1]
            point = points[segment_index]
            span = max(1, point[0] - previous[0])
            draw_y = previous[1] + int(
                (point[1] - previous[1]) * (draw_x - previous[0]) / span
            )
            fill_height = bottom - draw_y + 1
            column_width = min(3, x + width - draw_x)
            for band_index, band_color in enumerate(gradient_colors):
                band_top = draw_y + fill_height * band_index // 3
                band_bottom = draw_y + fill_height * (band_index + 1) // 3 - 1
                if band_bottom >= band_top:
                    canvas.fill_rect(
                        draw_x, band_top, column_width,
                        band_bottom - band_top + 1, band_color,
                    )
        previous = points[0]
        for point in points[1:]:
            canvas.line(previous[0], previous[1], point[0], point[1], color)
            previous = point

    def _draw_metric_card(self, canvas, y, title, data, color):
        """绘制 CPU、内存或 GPU 的百分比与渐变历史卡片。"""
        percent = int(self._number(data.get("percent")))
        usage_color = self._usage_color(percent)
        height = 50 if y == 2 else 43
        self._frame(canvas, 2, y, 100, height, color)
        canvas.text(7, y + 5, title, color, 1)
        history_y = y + 8
        history_height = height - 14
        if title == "CPU":
            temperature = data.get("temperature_c")
            temperature_text = "--C" if temperature is None else "{}C".format(
                int(self._number(temperature))
            )
            canvas.text(
                96 - canvas.text_width(temperature_text), y + 5,
                temperature_text, self._temperature_color(temperature), 1,
            )
            history_y = y + 18
            history_height = height - 24
        canvas.text(7, y + 18, "{}%".format(percent), usage_color, 2)
        self._gradient_history(
            canvas, 58, history_y, 38, history_height,
            data.get("history", ()), color, percentage=True,
        )

    def _draw_network_simple(self, canvas, snapshot):
        """绘制上传、下载速率及各自的渐变历史面积图。"""
        network = snapshot.get("network", {})
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        self._frame(canvas, 2, 147, 100, 66, BLUE)
        canvas.text(7, 152, "NET", BLUE, 1)
        ping = network.get("ping_ms")
        ping_text = "PERR" if ping is None else "P{}ms".format(
            int(self._number(ping))
        )
        canvas.text(
            96 - canvas.text_width(ping_text), 152,
            ping_text, self._ping_color(ping), 1,
        )
        canvas.text(7, 164, "UP " + self._format_rate(network.get("upload_bps"), unit), BLUE, 1)
        self._gradient_history(canvas, 7, 174, 89, 13, network.get("upload_history", ()), BLUE)
        canvas.text(7, 188, "DN " + self._format_rate(network.get("download_bps"), unit), GREEN, 1)
        self._gradient_history(canvas, 7, 198, 89, 11, network.get("download_history", ()), GREEN)

    def _draw_disk_cards(self, canvas, snapshot, selected_row=None):
        """按健康优先顺序纵向绘制最多三块物理磁盘。"""
        disks = self._selected_disks(snapshot)
        for index, disk in enumerate(disks):
            if selected_row is not None and index != selected_row:
                continue
            x, y = 106, 48 + index * 55
            percent = int(self._number(disk.get("percent")))
            usage_color = self._disk_usage_color(percent)
            frame_color, name_color, all_red, show_warning = self._health_display(
                disk.get("health", 0), usage_color
            )
            self._frame(canvas, x, y, 212, 52, frame_color)
            name = self._format_disk_name(disk.get("name", "DISK{}".format(index)), 8)
            canvas.text(x + 6, y + 5, "WARN" if show_warning else name, RED if all_red else name_color, 1)
            canvas.text(x + 6, y + 20, "{}%".format(percent), RED if all_red else usage_color, 2)
            capacity = self._format_disk_capacity(
                disk.get("used_bytes"), disk.get("total_bytes")
            )
            canvas.text(x + 6, y + 40, capacity, RED if all_red else WHITE, 1)
            self._bar(canvas, x + 67, y + 7, 98, 9, percent, RED if all_red else usage_color)
            health = int(self._number(disk.get("health")))
            health_text = "H{}".format(max(0, min(5, health)))
            health_x = x + 169
            canvas.text(
                health_x, y + 5, health_text,
                self._health_text_color(health), 1,
            )
            temperature = disk.get("temperature_c")
            temperature_text = "--C" if temperature is None else "{}C".format(
                int(self._number(temperature))
            )
            canvas.text(
                health_x + canvas.text_width(health_text) + 4, y + 5,
                temperature_text, self._temperature_color(temperature), 1,
            )
            canvas.text(x + 75, y + 22, "R " + self._format_rate(disk.get("read_bps"), "MB"), BLUE, 1)
            canvas.text(x + 75, y + 34, "W " + self._format_rate(disk.get("write_bps"), "MB"), GREEN, 1)
            self._gradient_history(canvas, x + 159, y + 20, 47, 12, disk.get("read_history", ()), BLUE)
            self._gradient_history(canvas, x + 159, y + 35, 47, 12, disk.get("write_history", ()), GREEN)

    def _draw_footer_simple(self, canvas, snapshot):
        """绘制当前时间和系统运行时长。"""
        self._frame(canvas, 2, 216, 316, 22, GRAY)
        timestamp = str(snapshot.get("timestamp", ""))
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        canvas.text(8, 223, clock, WHITE, 1)
        uptime = self._format_uptime(snapshot.get("uptime_seconds"))
        canvas.text(310 - canvas.text_width(uptime), 223, uptime, GRAY, 1)

    def draw_visible(self, canvas, snapshot):
        """绘制与当前画布条带相交的简洁仪表盘内容。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if self._visible(canvas, 2, 52):
            self._draw_metric_card(canvas, 2, "CPU", snapshot.get("cpu", {}), BLUE)
        if self._visible(canvas, 55, 98):
            self._draw_metric_card(canvas, 55, "MEM", snapshot.get("memory", {}), GREEN)
        if self._visible(canvas, 101, 144):
            self._draw_metric_card(canvas, 101, "GPU", snapshot.get("gpu") or {}, PURPLE)
        if self._visible(canvas, 147, 213):
            self._draw_network_simple(canvas, snapshot)
        if self._visible(canvas, 2, 45):
            self._draw_storage_summary(canvas, snapshot)
        if self._visible(canvas, 48, 210):
            self._draw_disk_cards(canvas, snapshot)
        if self._visible(canvas, 216, 238):
            self._draw_footer_simple(canvas, snapshot)

    def draw_dirty(self, canvas, key, snapshot):
        """仅重绘指定的简洁样式动态区域。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "cpu":
            self._draw_metric_card(canvas, 2, "CPU", snapshot.get("cpu", {}), BLUE)
        elif key == "memory":
            self._draw_metric_card(canvas, 55, "MEM", snapshot.get("memory", {}), GREEN)
        elif key == "gpu":
            self._draw_metric_card(canvas, 101, "GPU", snapshot.get("gpu") or {}, PURPLE)
        elif key == "network":
            self._draw_network_simple(canvas, snapshot)
        elif key == "storage_summary":
            self._draw_storage_summary(canvas, snapshot)
        elif key.startswith("disk_row_"):
            self._draw_disk_cards(canvas, snapshot, int(key[-1]))
        else:
            self._draw_footer_simple(canvas, snapshot)


def create_simple_style():
    """创建简洁横屏 LCD 仪表盘样式实例。"""
    return SimpleStyle()


register_style(SimpleStyle.name, create_simple_style)
