# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

"""实现游戏性能数据为核心的深色简约横屏监控样式。"""

from config import BLACK, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from styles.style_plugins import register_style


# 设计稿使用的高饱和强调色，均转换为 RGB565 色值。
GAME_CYAN = 0x05FC
GAME_ORANGE = 0xFC40


class GameStyle:
    """绘制 FPS 主卡、硬件摘要卡和三组使用率趋势图。"""

    name = "game"
    zh_name = "游戏监控简约"
    type = "builtin"
    idle = False
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    @staticmethod
    def create_dirty_regions():
        """返回按数据归属和画布容量拆分的九个动态刷新区域。"""
        return [
            ("header", 0, 0, 320, 25),
            ("fps_top", 5, 29, 155, 61),
            ("fps_bottom", 5, 90, 155, 60),
            ("cpu_summary", 164, 29, 151, 37),
            ("gpu_summary", 164, 70, 151, 37),
            ("memory_summary", 164, 111, 151, 37),
            ("cpu_chart", 5, 155, 100, 80),
            ("gpu_chart", 110, 155, 100, 80),
            ("memory_chart", 215, 155, 100, 80),
        ]

    @staticmethod
    def select_dirty_regions(previous, current):
        """仅选择数据实际发生变化的标题、摘要卡或趋势卡。"""
        regions = {region[0]: region for region in GameStyle.create_dirty_regions()}
        selected = []
        previous_fps = previous.get("fps") or {}
        current_fps = current.get("fps") or {}
        if (
            previous.get("timestamp") != current.get("timestamp")
            or previous_fps.get("process_name") != current_fps.get("process_name")
        ):
            selected.append(regions["header"])
        fps_fields = ("value", "history")
        if any(previous_fps.get(key) != current_fps.get(key) for key in fps_fields):
            selected.append(regions["fps_top"])
            selected.append(regions["fps_bottom"])
        for field, summary_key, summary_fields, chart_key in (
            (
                "cpu", "cpu_summary",
                ("percent", "frequency_ghz"), "cpu_chart",
            ),
            (
                "gpu", "gpu_summary",
                (
                    "percent", "dedicated_memory_used_bytes",
                    "dedicated_memory_total_bytes",
                ),
                "gpu_chart",
            ),
            (
                "memory", "memory_summary",
                ("percent", "used_bytes", "total_bytes"), "memory_chart",
            ),
        ):
            previous_data = previous.get(field) or {}
            current_data = current.get(field) or {}
            if any(
                previous_data.get(name) != current_data.get(name)
                for name in summary_fields
            ):
                selected.append(regions[summary_key])
            if (
                previous_data.get("percent") != current_data.get("percent")
                or previous_data.get("history") != current_data.get("history")
            ):
                selected.append(regions[chart_key])
        return selected

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断纵向组件是否与当前四十像素条带相交。"""
        origin = getattr(canvas, "origin_y", 0)
        height = getattr(canvas, "height", 240)
        return origin < bottom and origin + height > top

    @staticmethod
    def _number(value, default=0.0):
        """将可能为空或异常的快照字段安全转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _usage_color(cls, value):
        """按照低、中、较高和高负载等级返回百分比颜色。"""
        if value is None:
            return GRAY
        percent = cls._number(value)
        if percent < 60:
            return GREEN
        if percent < 80:
            return YELLOW
        if percent < 90:
            return GAME_ORANGE
        return RED

    @staticmethod
    def _frame(canvas, x, y, width, height, color=DARK):
        """使用单像素线条绘制低开销矩形卡片边框。"""
        canvas.fill_rect(x, y, width, 1, color)
        canvas.fill_rect(x, y + height - 1, width, 1, color)
        canvas.fill_rect(x, y, 1, height, color)
        canvas.fill_rect(x + width - 1, y, 1, height, color)

    @staticmethod
    def _right_text(canvas, right, y, value, color, scale=1):
        """以指定右边界绘制右对齐文本。"""
        text = str(value)
        canvas.text(right - canvas.text_width(text, scale), y, text, color, scale)

    @staticmethod
    def _fit_text(canvas, value, maximum_width, scale=1):
        """从右侧截短文本，确保进程名称不会覆盖顶栏时间。"""
        text = str(value)
        while text and canvas.text_width(text, scale) > maximum_width:
            text = text[:-1]
        return text

    @classmethod
    def _format_memory_usage(cls, used_bytes, total_bytes):
        """将显存或内存容量格式化为紧凑的已用量/总量 GiB 文本。"""
        gib = 1024 * 1024 * 1024
        total = cls._number(total_bytes) / gib
        if total <= 0:
            return "--/--G"
        used = cls._number(used_bytes) / gib
        used_text = "{:.1f}".format(used).rstrip("0").rstrip(".")
        total_text = "{:.1f}".format(total).rstrip("0").rstrip(".")
        return "{}/{}G".format(used_text, total_text)

    @classmethod
    def _history(cls, data, percentage=True):
        """返回最多二十四个非负历史采样，并按需约束百分比范围。"""
        values = [
            max(0, cls._number(value))
            for value in (data.get("history") or ())[-24:]
        ]
        if percentage:
            return [min(100, value) for value in values]
        return values

    @classmethod
    def _draw_history(
        cls, canvas, x, y, width, height, data, color, show_average=False,
    ):
        """绘制趋势折线、深色填充以及可选的平均值参考横线。"""
        values = cls._history(data, percentage=not show_average)
        maximum = max(100, max(values) * 1.05) if values else 100
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, GRAY)
        if len(values) < 2:
            return
        definition = {
            "x": x, "y": y, "width": width, "height": height,
            "maximum": maximum, "color": DARK, "filled": True,
            "regions": (), "grid_step_x": 0, "grid_step_y": 0,
            "grid_color": 0,
        }
        canvas.draw_line_chart(definition, values)
        definition["color"] = color
        definition["filled"] = False
        canvas.draw_line_chart(definition, values)
        if show_average:
            valid_values = [value for value in values if value > 0]
            if valid_values:
                average = sum(valid_values) / len(valid_values)
                average_y = y + height - 1 - int(
                    average * (height - 1) / maximum
                )
                average_y = max(y, min(y + height - 1, average_y))
                canvas.line(x, average_y, x + width - 1, average_y, WHITE)

    @classmethod
    def _draw_cpu_history(cls, canvas, x, y, width, height, data):
        """绘制按负载等级着色的 CPU 实心历史面积图。"""
        values = cls._history(data, percentage=True)
        canvas.line(x, y + height - 1, x + width - 1, y + height - 1, GRAY)
        if len(values) >= 2:
            canvas.draw_line_chart({
                "x": x, "y": y, "width": width, "height": height,
                "maximum": 100, "color": GREEN, "filled": True,
                "regions": (
                    (60, GREEN), (80, YELLOW),
                    (90, GAME_ORANGE), (101, RED),
                ),
                "grid_step_x": 0, "grid_step_y": 0, "grid_color": 0,
            }, values)
    @classmethod
    def _draw_fps_card(cls, canvas, snapshot):
        """绘制 FPS 当前值、最小值、平均值、最大值和短期趋势。"""
        fps = snapshot.get("fps") or {}
        current = fps.get("value")
        cls._frame(canvas, 5, 29, 155, 121)
        canvas.text(13, 39, "FPS", GAME_CYAN, 3)
        value_text = "--" if current is None else str(int(round(cls._number(current))))
        cls._right_text(canvas, 146, 39, value_text, GAME_CYAN, 3)
        values = [
            value for value in cls._history(fps, percentage=False)
            if value > 0
        ]
        minimum = min(values) if values else 0
        average = sum(values) / len(values) if values else 0
        maximum = max(values) if values else 0
        statistics = (
            ("MIN", minimum, GREEN),
            ("AVG", average, WHITE),
            ("MAX", maximum, GAME_ORANGE),
        )
        for index, statistic in enumerate(statistics):
            cls._draw_fps_statistic(
                canvas, 12 + index * 48,
                statistic[0], statistic[1], statistic[2],
            )
        cls._draw_history(
            canvas, 13, 109, 139, 32, fps, GAME_CYAN, show_average=True,
        )

    @classmethod
    def _draw_fps_statistic(cls, canvas, x, label, value, color):
        """在固定宽度统计列中居中绘制帧率名称和整数值。"""
        column_width = 43
        label_x = x + (column_width - canvas.text_width(label)) // 2
        value_text = str(min(999, int(round(cls._number(value)))))
        value_x = x + (column_width - canvas.text_width(value_text, 2)) // 2
        canvas.text(label_x, 76, label, GRAY, 1)
        canvas.text(value_x, 87, value_text, color, 2)

    @classmethod
    def _draw_summary_card(cls, canvas, y, label, data, color, detail):
        """首行大号显示名称和右对齐百分比，次行显示占用详情。"""
        raw_percent = data.get("percent")
        percent = int(round(cls._number(raw_percent)))
        percent_color = cls._usage_color(raw_percent)
        percent_text = "N/A" if label == "GPU" and raw_percent is None else "{}%".format(percent)
        cls._frame(canvas, 164, y, 151, 37)
        # 名称与百分比使用相同字号和基线，构成清晰的首行信息。
        canvas.text(171, y + 5, label, color, 2)
        cls._right_text(
            canvas, 309, y + 5, percent_text, percent_color, 2,
        )
        detail_text = str(detail)
        cls._right_text(canvas, 309, y + 25, detail_text[:10], WHITE, 1)

    @classmethod
    def _draw_metric_chart(cls, canvas, x, label, data, color):
        """绘制底部单项指标标题、当前值、刻度和历史趋势。"""
        cls._frame(canvas, x, 155, 100, 80)
        raw_percent = data.get("percent")
        percent = int(round(cls._number(raw_percent)))
        percent_color = cls._usage_color(raw_percent)
        percent_text = "N/A" if label == "GPU" and raw_percent is None else "{}%".format(percent)
        canvas.text(x + 7, 163, label, color, 2)
        cls._right_text(
            canvas, x + 93, 163, percent_text, percent_color, 2,
        )
        canvas.text(x + 7, 190, "100", GRAY, 1)
        canvas.text(x + 14, 218, "0", GRAY, 1)
        if label == "CPU":
            cls._draw_cpu_history(canvas, x + 29, 188, 64, 37, data)
        else:
            cls._draw_history(canvas, x + 29, 188, 64, 38, data, color)

    @classmethod
    def _draw_header(cls, canvas, snapshot):
        """绘制监听进程名称、时钟和顶栏分隔线。"""
        fps = snapshot.get("fps") or {}
        process_name = str(fps.get("process_name") or "NO GAME").upper()
        process_name = cls._fit_text(canvas, process_name, 218, 2)
        canvas.text(11, 7, process_name, WHITE, 2)
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:16] if len(timestamp) >= 16 else "--:--"
        cls._right_text(canvas, 309, 7, clock, WHITE, 2)
        canvas.line(0, 24, 319, 24, DARK)

    @classmethod
    def _draw(cls, canvas, snapshot):
        """按照设计稿比例绘制完整的游戏性能监控页面。"""
        canvas.clear(BLACK)
        cls._draw_header(canvas, snapshot)

        cpu = snapshot.get("cpu") or {}
        gpu = snapshot.get("gpu") or {}
        memory = snapshot.get("memory") or {}
        cls._draw_fps_card(canvas, snapshot)
        frequency = cpu.get("frequency_ghz")
        cpu_detail = "-- GHz" if frequency is None else "{:.1f}GHz".format(cls._number(frequency))
        gpu_memory_detail = cls._format_memory_usage(
            gpu.get("dedicated_memory_used_bytes"),
            gpu.get("dedicated_memory_total_bytes"),
        )
        memory_detail = cls._format_memory_usage(
            memory.get("used_bytes"), memory.get("total_bytes"),
        )
        cls._draw_summary_card(canvas, 29, "CPU", cpu, GREEN, cpu_detail)
        cls._draw_summary_card(
            canvas, 70, "GPU", gpu, PURPLE, gpu_memory_detail,
        )
        cls._draw_summary_card(canvas, 111, "RAM", memory, GAME_ORANGE, memory_detail)

        cls._draw_metric_chart(canvas, 5, "CPU", cpu, GREEN)
        cls._draw_metric_chart(canvas, 110, "GPU", gpu, PURPLE)
        cls._draw_metric_chart(canvas, 215, "RAM", memory, GAME_ORANGE)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """仅绘制与当前 LCD 条带相交的游戏监控组件。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        cpu = snapshot.get("cpu") or {}
        gpu = snapshot.get("gpu") or {}
        memory = snapshot.get("memory") or {}
        if cls._visible(canvas, 0, 25):
            cls._draw_header(canvas, snapshot)
        if cls._visible(canvas, 29, 150):
            cls._draw_fps_card(canvas, snapshot)
        if cls._visible(canvas, 29, 66):
            frequency = cpu.get("frequency_ghz")
            detail = "-- GHz" if frequency is None else "{:.1f}GHz".format(cls._number(frequency))
            cls._draw_summary_card(canvas, 29, "CPU", cpu, GREEN, detail)
        if cls._visible(canvas, 70, 107):
            detail = cls._format_memory_usage(
                gpu.get("dedicated_memory_used_bytes"),
                gpu.get("dedicated_memory_total_bytes"),
            )
            cls._draw_summary_card(canvas, 70, "GPU", gpu, PURPLE, detail)
        if cls._visible(canvas, 111, 148):
            detail = cls._format_memory_usage(
                memory.get("used_bytes"), memory.get("total_bytes"),
            )
            cls._draw_summary_card(canvas, 111, "RAM", memory, GAME_ORANGE, detail)
        if cls._visible(canvas, 155, 235):
            cls._draw_metric_chart(canvas, 5, "CPU", cpu, GREEN)
            cls._draw_metric_chart(canvas, 110, "GPU", gpu, PURPLE)
            cls._draw_metric_chart(canvas, 215, "RAM", memory, GAME_ORANGE)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """清空并仅重绘发生变化的独立游戏监控组件。"""
        snapshot = snapshot or {}
        canvas.clear(BLACK)
        if key == "header":
            cls._draw_header(canvas, snapshot)
        elif key.startswith("fps_"):
            cls._draw_fps_card(canvas, snapshot)
        elif key == "cpu_summary":
            cpu = snapshot.get("cpu") or {}
            frequency = cpu.get("frequency_ghz")
            detail = "-- GHz" if frequency is None else "{:.1f}GHz".format(cls._number(frequency))
            cls._draw_summary_card(canvas, 29, "CPU", cpu, GREEN, detail)
        elif key == "gpu_summary":
            gpu = snapshot.get("gpu") or {}
            detail = cls._format_memory_usage(
                gpu.get("dedicated_memory_used_bytes"),
                gpu.get("dedicated_memory_total_bytes"),
            )
            cls._draw_summary_card(canvas, 70, "GPU", gpu, PURPLE, detail)
        elif key == "memory_summary":
            memory = snapshot.get("memory") or {}
            detail = cls._format_memory_usage(
                memory.get("used_bytes"), memory.get("total_bytes"),
            )
            cls._draw_summary_card(canvas, 111, "RAM", memory, GAME_ORANGE, detail)
        else:
            definitions = {
                "cpu_chart": (5, "CPU", snapshot.get("cpu") or {}, GREEN),
                "gpu_chart": (110, "GPU", snapshot.get("gpu") or {}, PURPLE),
                "memory_chart": (
                    215, "RAM", snapshot.get("memory") or {}, GAME_ORANGE,
                ),
            }
            cls._draw_metric_chart(canvas, *definitions[key])


def create_game_style():
    """创建游戏监控简约样式实例。"""
    return GameStyle()


register_style(GameStyle.name, create_game_style)
