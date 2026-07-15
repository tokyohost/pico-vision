# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

"""实现参考像素热力表盘设计的横屏系统监控样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from styles.style_plugins import register_style


THERMAL_ORANGE = 0xFD20
THERMAL_BORDER = 0x3471


class ThermalWatchStyle:
    """封装热力表盘的卡片布局、指标格式和趋势图绘制规则。"""

    name = "thermal_watch"
    zh_name = "热力监控"
    type = "builtin"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    @staticmethod
    def create_dirty_regions():
        """创建不超过四十行条带缓冲容量的动态刷新区域。"""
        return [
            ("header", 2, 2, 316, 25),
            ("cpu_top", 2, 31, 198, 54),
            ("cpu_bottom", 2, 85, 198, 54),
            ("power", 204, 31, 114, 39),
            ("gpu", 204, 74, 114, 65),
            ("resource_cpu", 2, 143, 100, 37),
            ("resource_gpu", 106, 143, 90, 37),
            ("resource_memory", 200, 143, 118, 37),
            ("network", 2, 184, 316, 31),
            ("footer", 2, 219, 316, 19),
        ]

    @classmethod
    def select_dirty_regions(cls, previous, current):
        """根据可见数据的变化选择需要重绘的卡片区域。"""
        regions = {region[0]: region for region in cls.create_dirty_regions()}
        selected = []
        if previous.get("timestamp") != current.get("timestamp"):
            selected.append(regions["header"])
        if (previous.get("cpu") or {}) != (current.get("cpu") or {}):
            selected.extend((regions["cpu_top"], regions["cpu_bottom"], regions["resource_cpu"]))
        if (previous.get("gpu") or {}) != (current.get("gpu") or {}):
            selected.extend((regions["gpu"], regions["resource_gpu"]))
        if (previous.get("memory") or {}) != (current.get("memory") or {}):
            selected.append(regions["resource_memory"])
        previous_network = (
            previous.get("network"), previous.get("display", {}).get("network_unit"),
        )
        current_network = (
            current.get("network"), current.get("display", {}).get("network_unit"),
        )
        if previous_network != current_network:
            selected.append(regions["network"])
        if previous.get("power") != current.get("power"):
            selected.append(regions["power"])
        previous_footer = (previous.get("uptime_seconds"), previous.get("timestamp"))
        current_footer = (current.get("uptime_seconds"), current.get("timestamp"))
        if previous_footer != current_footer:
            selected.append(regions["footer"])
        return selected

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断指定纵向区域是否与当前条带画布相交。"""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    @staticmethod
    def _number(value, default=0):
        """安全地将快照字段转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _frame(canvas, x, y, width, height, color=THERMAL_BORDER):
        """绘制一像素卡片边框。"""
        canvas.line(x, y, x + width - 1, y, color)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, color)
        canvas.line(x, y, x, y + height - 1, color)
        canvas.line(x + width - 1, y, x + width - 1, y + height - 1, color)

    @staticmethod
    def _right_text(canvas, right, y, value, color, scale=1):
        """依据右边界对齐绘制文本。"""
        text = str(value)
        canvas.text(right - canvas.text_width(text, scale), y, text, color, scale)

    @staticmethod
    def _fit_text(canvas, value, max_width):
        """按像素宽度裁剪文本并在溢出时附加省略点。"""
        text = str(value or "")
        if canvas.text_width(text) <= max_width:
            return text
        suffix = "..."
        result = ""
        for character in text:
            if canvas.text_width(result + character + suffix) > max_width:
                break
            result += character
        return result + suffix

    @classmethod
    def _usage_color(cls, percent):
        """按照负载等级返回绿、黄、橙、红状态色。"""
        if percent is None:
            return GRAY
        value = max(0, min(100, cls._number(percent)))
        if value < 50:
            return GREEN
        if value < 75:
            return YELLOW
        if value < 90:
            return THERMAL_ORANGE
        return RED

    @classmethod
    def _temperature_color(cls, temperature):
        """按照温度等级返回冷色或告警色。"""
        if temperature is None:
            return GRAY
        value = cls._number(temperature)
        if value < 60:
            return BLUE
        if value < 80:
            return YELLOW
        return RED

    @classmethod
    def _format_rate(cls, value, unit):
        """按照显示设置将网络速率压缩到八个字符以内。"""
        amount = max(0, cls._number(value))
        if unit == "Mbps":
            amount *= 8
            units = ("bps", "Kbps", "Mbps", "Gbps")
        else:
            units = ("B/s", "K/s", "M/s", "G/s")
        index = 0
        while amount >= 1000 and index < len(units) - 1:
            amount /= 1000
            index += 1
        number = "{:.1f}".format(amount) if amount < 100 else str(int(round(amount)))
        return (number + units[index])[:8]

    @classmethod
    def _format_uptime(cls, seconds):
        """将运行秒数格式化为紧凑的天和时分秒文本。"""
        total = max(0, int(cls._number(seconds)))
        days, remainder = divmod(total, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return "{}D {:02d}:{:02d}".format(days, hours, minutes)
        return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)

    @staticmethod
    def _history(canvas, x, y, width, height, values, color, maximum=100):
        """提交带暗色网格的实心历史趋势图定义。"""
        canvas.draw_line_chart({
            "x": x, "y": y, "width": width, "height": height,
            "maximum": maximum, "color": color, "filled": True,
            "grid_step_x": max(8, width // 5),
            "grid_step_y": max(5, height // 3), "grid_color": DARK,
        }, values or ())

    @classmethod
    def _segmented_bar(cls, canvas, x, y, width, percent, color):
        """绘制参考图中的分段实心资源占用条。"""
        value = max(0, min(100, cls._number(percent)))
        segment_width, gap = 5, 2
        count = max(1, (width + gap) // (segment_width + gap))
        active = int(round(count * value / 100))
        for index in range(count):
            segment_x = x + index * (segment_width + gap)
            actual_width = min(segment_width, x + width - segment_x)
            if actual_width > 0:
                canvas.fill_rect(segment_x, y, actual_width, 7, color if index < active else DARK)

    @classmethod
    def _draw_header(cls, canvas, snapshot):
        """绘制表盘标题、在线指示和当前时间。"""
        canvas.line(2, 26, 317, 26, THERMAL_BORDER)
        canvas.text(8, 8, "THERMAL WATCH", WHITE, 1)
        network = snapshot.get("network") or {}
        canvas.fill_rect(220, 11, 5, 5, GREEN if network.get("online") else RED)
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:16] if len(timestamp) >= 16 else "--:--"
        cls._right_text(canvas, 312, 7, clock, WHITE, 2)

    @classmethod
    def _draw_cpu(cls, canvas, snapshot):
        """绘制大号 CPU 温度、频率、占用率和温度实心趋势。"""
        cpu = snapshot.get("cpu") or {}
        temperature, percent = cpu.get("temperature_c"), cpu.get("percent")
        cls._frame(canvas, 2, 31, 198, 108, RED)
        canvas.text(8, 38, "CPU TEMP", WHITE, 1)
        temperature_text = "--℃" if temperature is None else "{}℃".format(int(cls._number(temperature)))
        canvas.text(8, 52, temperature_text, cls._temperature_color(temperature), 4)
        frequency = cpu.get("frequency_ghz")
        frequency_text = "-- GHz" if frequency is None else "{:.2f} GHz".format(cls._number(frequency))
        cls._right_text(canvas, 192, 58, frequency_text, WHITE, 1)
        percent_text = "--%" if percent is None else "{}%".format(int(cls._number(percent)))
        cls._right_text(canvas, 192, 76, percent_text, GRAY, 2)
        cls._history(canvas, 8, 101, 184, 30, cpu.get("history"), RED)

    @classmethod
    def _draw_power(cls, canvas, snapshot):
        """绘制实时功耗卡片。"""
        cls._frame(canvas, 204, 31, 114, 39, BLUE)
        canvas.text(210, 37, "POWER", WHITE, 1)
        watts = (snapshot.get("power") or {}).get("watts")
        value = "--.-" if watts is None else "{:.1f}".format(cls._number(watts))
        canvas.text(210, 50, value, RED, 2)
        cls._right_text(canvas, 312, 54, "W", WHITE, 1)

    @classmethod
    def _draw_gpu(cls, canvas, snapshot):
        """使用原 GPU 与环境温度空间绘制温度、占用率和实心趋势。"""
        gpu = snapshot.get("gpu") or {}
        temperature = gpu.get("temperature_c") or gpu.get("temperature")
        percent = gpu.get("percent")
        cls._frame(canvas, 204, 74, 114, 65, BLUE)
        canvas.text(210, 80, "GPU", WHITE, 1)
        temp_text = "--℃" if temperature is None else "{}℃".format(int(cls._number(temperature)))
        canvas.text(210, 94, temp_text, cls._temperature_color(temperature), 2)
        percent_text = "N/A" if percent is None else "{}%".format(int(cls._number(percent)))
        cls._right_text(canvas, 312, 94, percent_text, cls._usage_color(percent), 2)
        cls._history(canvas, 210, 116, 102, 17, gpu.get("history"), BLUE)

    @classmethod
    def _draw_resource_card(cls, canvas, x, width, title, data, color):
        """绘制 CPU、GPU 或内存的分段占用率卡片。"""
        percent = data.get("percent")
        cls._frame(canvas, x, 143, width, 37, color)
        canvas.text(x + 6, 149, title, WHITE, 1)
        percent_text = "--%" if percent is None else "{}%".format(int(cls._number(percent)))
        cls._right_text(canvas, x + width - 6, 149, percent_text, color, 1)
        cls._segmented_bar(canvas, x + 6, 165, width - 12, percent, color)

    @classmethod
    def _draw_network(cls, canvas, snapshot):
        """在原 SSD 与 NET 整行空间绘制完整网络状态和双向实心趋势。"""
        network = snapshot.get("network") or {}
        unit = snapshot.get("display", {}).get("network_unit", "MB")
        cls._frame(canvas, 2, 184, 316, 31, BLUE)
        canvas.line(100, 185, 100, 213, THERMAL_BORDER)
        canvas.line(208, 185, 208, 213, THERMAL_BORDER)
        ping = network.get("ping_ms")
        ping_text = "ERR" if ping is None else "{}ms".format(int(cls._number(ping)))
        canvas.text(8, 189, "NET", BLUE, 1)
        ping_color = GREEN if ping is not None and cls._number(ping) < 100 else RED
        cls._right_text(canvas, 94, 189, ping_text, ping_color, 1)
        canvas.text(8, 201, cls._fit_text(canvas, network.get("ip") or "0.0.0.0", 86), WHITE if network.get("online") else GRAY, 1)
        canvas.text(106, 189, "UP", BLUE, 1)
        canvas.text(128, 189, cls._format_rate(network.get("upload_bps"), unit), WHITE, 1)
        cls._history(canvas, 106, 201, 96, 8, network.get("upload_history"), BLUE, 0)
        canvas.text(214, 189, "DN", GREEN, 1)
        canvas.text(236, 189, cls._format_rate(network.get("download_bps"), unit), WHITE, 1)
        cls._history(canvas, 214, 201, 98, 8, network.get("download_history"), GREEN, 0)

    @classmethod
    def _draw_footer(cls, canvas, snapshot):
        """绘制运行时长和日期页脚。"""
        canvas.line(2, 219, 317, 219, THERMAL_BORDER)
        canvas.text(8, 225, "UP " + cls._format_uptime(snapshot.get("uptime_seconds")), WHITE, 1)
        timestamp = str(snapshot.get("timestamp") or "")
        cls._right_text(canvas, 312, 225, timestamp[:10] if len(timestamp) >= 10 else "---- -- --", WHITE, 1)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制当前条带内全部可见的热力监控组件。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if cls._visible(canvas, 2, 27):
            cls._draw_header(canvas, snapshot)
        if cls._visible(canvas, 31, 139):
            cls._draw_cpu(canvas, snapshot)
        if cls._visible(canvas, 31, 70):
            cls._draw_power(canvas, snapshot)
        if cls._visible(canvas, 74, 139):
            cls._draw_gpu(canvas, snapshot)
        if cls._visible(canvas, 143, 180):
            cls._draw_resource_card(canvas, 2, 100, "CPU", snapshot.get("cpu") or {}, THERMAL_ORANGE)
            cls._draw_resource_card(canvas, 106, 90, "GPU", snapshot.get("gpu") or {}, BLUE)
            cls._draw_resource_card(canvas, 200, 118, "RAM", snapshot.get("memory") or {}, PURPLE)
        if cls._visible(canvas, 184, 215):
            cls._draw_network(canvas, snapshot)
        if cls._visible(canvas, 219, 238):
            cls._draw_footer(canvas, snapshot)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """清空并重绘指定动态区域对应的完整卡片。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "header":
            cls._draw_header(canvas, snapshot)
        elif key.startswith("cpu_"):
            cls._draw_cpu(canvas, snapshot)
        elif key == "power":
            cls._draw_power(canvas, snapshot)
        elif key == "gpu":
            cls._draw_gpu(canvas, snapshot)
        elif key == "resource_cpu":
            cls._draw_resource_card(canvas, 2, 100, "CPU", snapshot.get("cpu") or {}, THERMAL_ORANGE)
        elif key == "resource_gpu":
            cls._draw_resource_card(canvas, 106, 90, "GPU", snapshot.get("gpu") or {}, BLUE)
        elif key == "resource_memory":
            cls._draw_resource_card(canvas, 200, 118, "RAM", snapshot.get("memory") or {}, PURPLE)
        elif key == "network":
            cls._draw_network(canvas, snapshot)
        elif key == "footer":
            cls._draw_footer(canvas, snapshot)


def create_thermal_watch_style():
    """创建热力监控 LCD 样式插件。"""
    return ThermalWatchStyle()


register_style(ThermalWatchStyle.name, create_thermal_watch_style)
