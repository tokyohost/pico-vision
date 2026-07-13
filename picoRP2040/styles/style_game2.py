# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

"""实现面向游戏监控的横向紧凑仪表盘样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from styles.style_plugins import register_style


# Element UI 经典状态色转换后的 RGB565 色值。
ELEMENT_SUCCESS = 0x6607
ELEMENT_WARNING = 0xE507
ELEMENT_DANGER = 0xF36D
NETWORK_RATE_MAX_CHARS = 8


class Game2Style:
    """封装游戏 FPS、CPU、GPU、内存和网络的横屏监控绘制规则。"""

    name = "game2"
    zh_name = "游戏监控 PICO"
    type = "builtin"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    @staticmethod
    def create_dirty_regions():
        """创建不超过条带缓冲容量的动态刷新区域。"""
        return [
            ("header", 2, 2, 316, 25),
            ("fps_top", 2, 31, 154, 43),
            ("fps_bottom", 2, 74, 154, 43),
            ("cpu", 160, 31, 158, 55),
            ("memory", 160, 90, 158, 55),
            ("gpu_top", 2, 121, 154, 44),
            ("gpu_bottom", 2, 165, 154, 43),
            ("network", 160, 149, 158, 59),
            ("footer", 2, 212, 316, 26),
        ]

    @classmethod
    def select_dirty_regions(cls, previous, current):
        """根据相邻快照差异仅返回实际变化的游戏监控卡片。"""
        regions = {region[0]: region for region in cls.create_dirty_regions()}
        selected = []
        previous_fps = previous.get("fps") or {}
        current_fps = current.get("fps") or {}
        if (
            previous.get("timestamp") != current.get("timestamp")
            or previous_fps.get("process_name") != current_fps.get("process_name")
        ):
            selected.append(regions["header"])
        if previous_fps != current_fps:
            selected.append(regions["fps_top"])
            selected.append(regions["fps_bottom"])
        for key in ("cpu", "memory"):
            if (previous.get(key) or {}) != (current.get(key) or {}):
                selected.append(regions[key])
        if (previous.get("gpu") or {}) != (current.get("gpu") or {}):
            selected.append(regions["gpu_top"])
            selected.append(regions["gpu_bottom"])
        previous_network = (
            previous.get("network"),
            previous.get("display", {}).get("network_unit"),
        )
        current_network = (
            current.get("network"),
            current.get("display", {}).get("network_unit"),
        )
        if previous_network != current_network:
            selected.append(regions["network"])
        previous_footer = (
            previous.get("timestamp"),
            previous.get("uptime_seconds"),
            previous.get("power"),
        )
        current_footer = (
            current.get("timestamp"),
            current.get("uptime_seconds"),
            current.get("power"),
        )
        if previous_footer != current_footer:
            selected.append(regions["footer"])
        return selected

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断指定区域是否与当前条带视口相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    @staticmethod
    def _number(value, default=0):
        """安全地把快照值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _frame(canvas, x, y, width, height, color):
        """绘制一像素矩形边框。"""
        canvas.line(x, y, x + width - 1, y, color)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, color)
        canvas.line(x, y, x, y + height - 1, color)
        canvas.line(x + width - 1, y, x + width - 1, y + height - 1, color)

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
    def _fps_color(cls, value):
        """按照游戏帧率状态返回醒目的状态色。"""
        if value is None:
            return GRAY
        fps = cls._number(value)
        if fps >= 90:
            return ELEMENT_SUCCESS
        if fps >= 55:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

    @classmethod
    def _fps_values(cls, fps):
        """提取有效 FPS 历史采样，缺少历史时回退到当前帧率。"""
        values = []
        for value in fps.get("history") or ():
            sample = cls._number(value, -1)
            if sample >= 0:
                values.append(sample)
        current = fps.get("value")
        if not values and current is not None:
            values.append(cls._number(current))
        return values

    @classmethod
    def _fps_jitter(cls, values):
        """计算相邻 FPS 采样的平均绝对差，作为短期帧率抖动。"""
        if len(values) < 2:
            return 0
        total = 0
        previous = values[0]
        for value in values[1:]:
            total += abs(value - previous)
            previous = value
        return total / (len(values) - 1)

    @classmethod
    def _draw_fps_stat(cls, canvas, x, label, value, color):
        """绘制 FPS 统计项的紧凑标签和值。"""
        value_text = "--" if value is None else str(min(999, int(round(cls._number(value)))))
        canvas.text(x, 74, label, GRAY, 1)
        canvas.text(x, 85, value_text, color, 1)

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
    def _ping_color(cls, ping_ms):
        """按照网络延迟分级返回状态颜色。"""
        if ping_ms is None:
            return ELEMENT_DANGER
        value = max(0, cls._number(ping_ms))
        if value < 50:
            return ELEMENT_SUCCESS
        if value < 100:
            return ELEMENT_WARNING
        return ELEMENT_DANGER

    @classmethod
    def _bar(cls, canvas, x, y, width, height, percent, color):
        """绘制实心百分比进度条，避免圆角在低性能设备上增加开销。"""
        value = max(0, min(100, cls._number(percent)))
        canvas.fill_rect(x, y, width, height, DARK)
        filled_width = int(width * value / 100)
        if filled_width > 0:
            canvas.fill_rect(x, y, filled_width, height, color)

    @staticmethod
    def _history(
        canvas, x, y, width, height, values, color,
        percentage=False, color_by_value=False,
    ):
        """提交历史图定义，由 Canvas 统一完成抽样、填充和分段配色。"""
        regions = (
            ((50, ELEMENT_SUCCESS), (80, ELEMENT_WARNING),
             (101, ELEMENT_DANGER))
            if color_by_value else ()
        )
        canvas.draw_line_chart({
            "x": x, "y": y, "width": width, "height": height,
            "maximum": 100 if percentage else 0,
            "color": color, "filled": True, "regions": regions,
            "grid_step_x": 12, "grid_step_y": 7,
            "grid_color": GRAY,
        }, values or ())

    @staticmethod
    def _right_text(canvas, right, y, value, color, scale=1):
        """按右边界绘制文本。"""
        text = str(value)
        canvas.text(right - canvas.text_width(text, scale), y, text, color, scale)

    @staticmethod
    def _fit_text(canvas, text, max_width):
        """按实际像素宽度裁剪文本，超出可用区域时追加省略号。"""
        text = str(text or "")
        if max_width <= 0:
            return ""
        if canvas.text_width(text) <= max_width:
            return text
        ellipsis = "..."
        ellipsis_width = canvas.text_width(ellipsis)
        if ellipsis_width > max_width:
            return ""
        result = ""
        for character in text:
            candidate = result + character
            if canvas.text_width(candidate) + ellipsis_width > max_width:
                break
            result = candidate
        return result + ellipsis

    @classmethod
    def _format_bytes(cls, value):
        """把字节数格式化为适合小卡片显示的容量文本。"""
        amount = max(0, cls._number(value))
        for unit in ("B", "K", "M", "G", "T"):
            if amount < 1024 or unit == "T":
                return ("{:.1f}{}" if unit in ("G", "T") else "{:.0f}{}").format(amount, unit)
            amount /= 1024
        return "0B"

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
    def _format_uptime(cls, seconds):
        """把运行秒数格式化为天数与时分秒文本。"""
        total_seconds = max(0, int(cls._number(seconds)))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "{}D {:02d}:{:02d}:{:02d}".format(days, hours, minutes, seconds)

    @classmethod
    def _draw_header(cls, canvas, snapshot):
        """绘制顶部游戏进程名和时钟。"""
        cls._frame(canvas, 2, 2, 316, 25, BLUE)
        fps = snapshot.get("fps") or {}
        process = str(fps.get("process_name") or "NO GAME").upper()
        canvas.text(8, 9, cls._fit_text(canvas, process, 220), WHITE, 1)
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        cls._right_text(canvas, 312, 9, clock, WHITE, 1)

    @classmethod
    def _draw_fps(cls, canvas, snapshot):
        """绘制当前帧率、平均最高最低抖动和帧率历史趋势。"""
        fps = snapshot.get("fps") or {}
        value = fps.get("value")
        color = cls._fps_color(value)
        cls._frame(canvas, 2, 31, 154, 86, YELLOW)
        canvas.text(8, 39, "FPS", YELLOW, 2)
        value_text = "--" if value is None else str(int(round(cls._number(value))))
        scale = 4 if len(value_text) <= 3 else 3
        cls._right_text(canvas, 150, 38, value_text, color, scale)
        values = cls._fps_values(fps)
        average = sum(values) / len(values) if values else None
        maximum = max(values) if values else None
        minimum = min(values) if values else None
        jitter = cls._fps_jitter(values) if values else None
        cls._draw_fps_stat(canvas, 8, "AVG", average, WHITE)
        cls._draw_fps_stat(canvas, 44, "MAX", maximum, ELEMENT_SUCCESS)
        cls._draw_fps_stat(canvas, 80, "MIN", minimum, color)
        cls._draw_fps_stat(canvas, 116, "JIT", jitter, YELLOW)
        cls._history(canvas, 8, 103, 142, 10, fps.get("history"), color)

    @classmethod
    def _draw_cpu(cls, canvas, snapshot):
        """绘制 CPU 占用率、温度、频率和短历史趋势。"""
        cpu = snapshot.get("cpu") or {}
        percent = int(cls._number(cpu.get("percent")))
        color = cls._usage_color(percent)
        temperature = cpu.get("temperature_c") or cpu.get("temperature")
        cls._frame(canvas, 160, 31, 158, 55, GREEN)
        canvas.text(166, 38, "CPU", GREEN, 1)
        percent_text = "{}%".format(percent)
        cls._right_text(canvas, 312, 36, percent_text, color, 2)
        temp_text = "--℃" if temperature is None else "{}℃".format(int(cls._number(temperature)))
        canvas.text(166, 55, temp_text, cls._temperature_color(temperature), 1)
        frequency = cpu.get("frequency_ghz")
        freq_text = "--GHz" if frequency is None else "{:.2f}GHz".format(cls._number(frequency))
        cls._right_text(canvas, 312, 55, freq_text, WHITE, 1)
        cls._bar(canvas, 166, 68, 146, 5, percent, color)
        cls._history(
            canvas, 166, 75, 146, 8, cpu.get("history"), color,
            percentage=True, color_by_value=True,
        )

    @classmethod
    def _draw_gpu(cls, canvas, snapshot):
        """绘制左下角 GPU 占用率、温度、显存和历史趋势。"""
        gpu = snapshot.get("gpu") or {}
        raw_percent = gpu.get("percent")
        percent = int(cls._number(raw_percent))
        color = cls._usage_color(percent)
        temperature = gpu.get("temperature_c") or gpu.get("temperature")
        cls._frame(canvas, 2, 121, 154, 87, PURPLE)
        canvas.text(8, 128, "GPU", PURPLE, 1)
        percent_text = "N/A" if raw_percent is None else "{}%".format(percent)
        cls._right_text(canvas, 150, 126, percent_text, color, 2)
        temp_text = "--℃" if temperature is None else "{}℃".format(int(cls._number(temperature)))
        canvas.text(8, 148, temp_text, cls._temperature_color(temperature), 1)
        used_vram = gpu.get("dedicated_memory_used_bytes")
        total_vram = gpu.get("dedicated_memory_total_bytes")
        if total_vram:
            vram_text = "VRAM " + cls._format_bytes(used_vram) + "/" + cls._format_bytes(total_vram)
        else:
            vram_text = "VRAM --/--"
        cls._right_text(canvas, 150, 148, cls._fit_text(canvas, vram_text, 92), WHITE, 1)
        cls._bar(canvas, 8, 163, 142, 8, percent, color)
        cls._history(
            canvas, 8, 176, 142, 27, gpu.get("history"), color,
            percentage=True, color_by_value=True,
        )

    @classmethod
    def _draw_memory(cls, canvas, snapshot):
        """绘制右侧紧凑内存占用率、容量和短历史趋势。"""
        memory = snapshot.get("memory") or {}
        percent = int(cls._number(memory.get("percent")))
        color = cls._usage_color(percent)
        cls._frame(canvas, 160, 90, 158, 55, PURPLE)
        canvas.text(166, 97, "MEM", PURPLE, 1)
        percent_text = "{}%".format(percent)
        cls._right_text(canvas, 312, 95, percent_text, color, 2)
        used_text = cls._format_bytes(memory.get("used_bytes"))
        total_text = cls._format_bytes(memory.get("total_bytes"))
        if used_text[-1:] == total_text[-1:]:
            used_text = used_text[:-1]
        detail = used_text + "/" + total_text
        canvas.text(166, 114, cls._fit_text(canvas, detail, 88), WHITE, 1)
        cls._bar(canvas, 166, 127, 146, 5, percent, color)
        cls._history(canvas, 166, 134, 146, 8, memory.get("history"), color, percentage=True)

    @classmethod
    def _draw_network(cls, canvas, snapshot):
        """绘制网络上下行速率、延迟和下载趋势。"""
        network = snapshot.get("network") or {}
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        cls._frame(canvas, 160, 149, 158, 59, BLUE)
        canvas.text(166, 156, "NET", BLUE, 1)
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}ms".format(int(cls._number(ping)))
        cls._right_text(canvas, 312, 156, ping_text, cls._ping_color(ping), 1)
        canvas.text(166, 169, "UP", WHITE, 1)
        canvas.text(190, 169, cls._format_rate(network.get("upload_bps"), unit), BLUE, 1)
        canvas.text(166, 183, "DN", WHITE, 1)
        canvas.text(190, 183, cls._format_rate(network.get("download_bps"), unit), GREEN, 1)
        cls._history(canvas, 245, 169, 67, 12, network.get("upload_history"), BLUE)
        cls._history(canvas, 245, 190, 67, 13, network.get("download_history"), GREEN)

    @classmethod
    def _draw_footer(cls, canvas, snapshot):
        """绘制底部运行时长、功耗和累计网络流量。"""
        cls._frame(canvas, 2, 212, 316, 26, BLUE)
        canvas.text(8, 220, "UPTIME", BLUE, 1)
        canvas.text(65, 220, cls._format_uptime(snapshot.get("uptime_seconds")), WHITE, 1)
        canvas.line(174, 216, 174, 233, BLUE)
        watts = snapshot.get("power", {}).get("watts")
        power_text = "--W" if watts is None else "{:.0f}W".format(cls._number(watts))
        canvas.text(182, 220, "PWR", BLUE, 1)
        canvas.text(215, 220, power_text, YELLOW, 1)
        network = snapshot.get("network") or {}
        total_text = cls._format_bytes(network.get("receive_bytes"))
        cls._right_text(canvas, 312, 220, "RX " + total_text, GREEN, 1)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制与当前条带相交的游戏监控仪表盘内容。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if cls._visible(canvas, 2, 27):
            cls._draw_header(canvas, snapshot)
        if cls._visible(canvas, 31, 117):
            cls._draw_fps(canvas, snapshot)
        if cls._visible(canvas, 31, 86):
            cls._draw_cpu(canvas, snapshot)
        if cls._visible(canvas, 90, 145):
            cls._draw_memory(canvas, snapshot)
        if cls._visible(canvas, 121, 208):
            cls._draw_gpu(canvas, snapshot)
        if cls._visible(canvas, 149, 208):
            cls._draw_network(canvas, snapshot)
        if cls._visible(canvas, 212, 238):
            cls._draw_footer(canvas, snapshot)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """仅重绘指定的动态数据卡片。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "header":
            cls._draw_header(canvas, snapshot)
        elif key.startswith("fps_"):
            cls._draw_fps(canvas, snapshot)
        elif key == "cpu":
            cls._draw_cpu(canvas, snapshot)
        elif key.startswith("gpu_"):
            cls._draw_gpu(canvas, snapshot)
        elif key == "memory":
            cls._draw_memory(canvas, snapshot)
        elif key == "network":
            cls._draw_network(canvas, snapshot)
        else:
            cls._draw_footer(canvas, snapshot)


def create_game2_style():
    """创建游戏监控横向紧凑样式实例。"""
    return Game2Style()


register_style(Game2Style.name, create_game2_style)
