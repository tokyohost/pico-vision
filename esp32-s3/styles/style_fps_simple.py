# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

"""实现参考深色仪表盘设计的 FPS 监控简约横屏样式。"""

from config import BLACK, DARK, GRAY, GREEN, RED, WHITE
from styles.style_plugins import register_style


# Element UI 经典语义色转换后的 RGB565 色值。
ELEMENT_PRIMARY = 0x44FF
ELEMENT_SUCCESS = 0x6607
ELEMENT_WARNING = 0xE507
ELEMENT_DANGER = 0xF36D
ELEMENT_INFO = 0x9493


class FpsSimpleStyle:
    """以当前帧率、短期趋势和核心统计为重点绘制 FPS 仪表盘。"""

    name = "fps_simple"
    zh_name = "FPS 监控简约"
    type = "builtin"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"
    _prepared_snapshot = None
    _prepared_data = None

    @staticmethod
    def create_dirty_regions():
        """返回五个主体条带和一个独立来源状态区域。"""
        regions = [
            ("fps_simple_strip_{}".format(index), 0, index * 40, 320, 40)
            for index in range(5)
        ]
        regions.append(("fps_simple_source", 0, 211, 320, 29))
        return regions

    @staticmethod
    def select_dirty_regions(previous, current):
        """按时间、FPS 数据与来源状态差异选择最小刷新条带。"""
        regions = FpsSimpleStyle.create_dirty_regions()
        selected = []
        previous_fps = previous.get("fps") or {}
        current_fps = current.get("fps") or {}
        if previous.get("timestamp") != current.get("timestamp"):
            selected.append(regions[0])
        if (
            previous_fps.get("value") != current_fps.get("value")
            or previous_fps.get("history") != current_fps.get("history")
        ):
            selected.extend(region for region in regions[:5] if region not in selected)
        footer_fields = ("value", "source", "process_name")
        if any(previous_fps.get(field) != current_fps.get(field) for field in footer_fields):
            selected.append(regions[5])
        return selected

    @staticmethod
    def _number(value, default=0.0):
        """将可能为空的快照字段安全转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _history(cls, fps):
        """返回最近二十四个非负 FPS 采样值。"""
        values = []
        for value in fps.get("history") or ():
            number = cls._number(value, -1)
            if number >= 0:
                values.append(number)
        return values[-24:]

    @classmethod
    def prepare_frame(cls, snapshot):
        """每帧仅计算一次历史与统计数据，供六个显示条带共同复用。"""
        fps = snapshot.get("fps") or {}
        values = cls._history(fps)
        valid_values = [value for value in values if value > 0]
        average = sum(valid_values) / len(valid_values) if valid_values else 0
        jitter = 0
        if len(valid_values) > 1:
            jitter = sum(
                abs(valid_values[index] - valid_values[index - 1])
                for index in range(1, len(valid_values))
            ) / (len(valid_values) - 1)
        cls._prepared_snapshot = snapshot
        cls._prepared_data = (
            fps,
            values,
            average,
            min(valid_values) if valid_values else 0,
            max(valid_values) if valid_values else 0,
            jitter,
        )

    @staticmethod
    def _frame(canvas, x, y, width, height, color=GRAY):
        """绘制低开销的单像素矩形边框。"""
        canvas.fill_rect(x, y, width, 1, color)
        canvas.fill_rect(x, y + height - 1, width, 1, color)
        canvas.fill_rect(x, y, 1, height, color)
        canvas.fill_rect(x + width - 1, y, 1, height, color)

    @staticmethod
    def _right_text(canvas, right, y, value, color, scale=1):
        """按照指定右边界对齐绘制文本。"""
        text = str(value)
        canvas.text(right - canvas.text_width(text, scale), y, text, color, scale)

    @classmethod
    def _draw_chart(cls, canvas, values, average):
        """通过 Canvas 批量接口绘制趋势、网格和平均值参考线。"""
        x, y, width, height = 110, 30, 202, 124
        maximum = max(100.0, max(values) * 1.08) if values else 100.0
        cls._right_text(canvas, 106, y, int(maximum), ELEMENT_INFO)
        cls._right_text(canvas, 106, y + height - 8, "0", ELEMENT_INFO)
        canvas.draw_grid(x, y, width, height, 55, 31, DARK)
        if len(values) < 2:
            canvas.text(132, 94, "WAITING FOR FPS", GRAY, 1)
            return
        canvas.draw_line_chart({
            "x": x, "y": y, "width": width, "height": height,
            "maximum": maximum, "color": DARK, "filled": True,
            "regions": (), "grid_step_x": 0, "grid_step_y": 0,
            "grid_color": 0,
        }, values)
        canvas.draw_line_chart({
            "x": x, "y": y, "width": width, "height": height,
            "maximum": maximum, "color": ELEMENT_SUCCESS, "filled": False,
            "regions": (), "grid_step_x": 0, "grid_step_y": 0,
            "grid_color": 0,
        }, values)
        average_y = y + height - 1 - int(average * (height - 1) / maximum)
        average_y = max(y, min(y + height - 1, average_y))
        canvas.line(x, average_y, x + width - 1, average_y, ELEMENT_PRIMARY)
        cls._right_text(canvas, 312, 146, "NOW", ELEMENT_INFO)

    @classmethod
    def _draw_stat_card(cls, canvas, x, width, label, value, color):
        """绘制底部单个统计卡片。"""
        cls._frame(canvas, x, 163, width, 37, DARK)
        label_x = x + (width - canvas.text_width(label)) // 2
        value_text = str(value)
        value_x = x + (width - canvas.text_width(value_text, 2)) // 2
        canvas.text(label_x, 166, label, color, 1)
        canvas.text(value_x, 180, value_text, color, 2)

    @classmethod
    def _draw(cls, canvas, snapshot):
        """绘制完整的 FPS 监控简约仪表盘。"""
        if cls._prepared_snapshot is not snapshot or cls._prepared_data is None:
            cls.prepare_frame(snapshot)
        fps, values, average, minimum, maximum, jitter = cls._prepared_data
        current = fps.get("value")
        value_text = "N/A" if current is None else str(int(round(cls._number(current))))

        canvas.clear(BLACK)
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        cls._right_text(canvas, 312, 7, clock, GRAY)
        canvas.line(7, 21, 312, 21, DARK)

        canvas.text(8, 30, "LIVE FPS", GREEN, 1)
        value_x = 8 + (74 - canvas.text_width(value_text, 4)) // 2
        canvas.text(max(8, value_x), 53, value_text, WHITE if current is not None else GRAY, 4)
        canvas.text(8, 91, "ACTIVE" if current is not None else "NO DATA", GREEN if current is not None else GRAY, 1)
        cls._draw_chart(canvas, values, average)

        cards = (
            ("AVG", int(round(average)), ELEMENT_PRIMARY),
            ("MIN", int(round(minimum)), ELEMENT_SUCCESS),
            ("MAX", int(round(maximum)), ELEMENT_DANGER),
            ("JITTER", int(round(jitter)), ELEMENT_WARNING),
        )
        card_width = 74
        for index, card in enumerate(cards):
            cls._draw_stat_card(canvas, 6 + index * 77, card_width, card[0], card[1], card[2])

        source = str(fps.get("source") or "unavailable").upper()
        process_name = str(fps.get("process_name") or "--")
        status_color = GREEN if current is not None else RED
        canvas.text(8, 220, "SOURCE", GREEN, 1)
        canvas.text(55, 220, source[:15], WHITE if current is not None else GRAY, 1)
        cls._right_text(canvas, 312, 220, process_name[:18], status_color)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制与当前条带画布相交的简约 FPS 页面。"""
        cls._draw(canvas, snapshot or {})

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """重绘简约 FPS 页面中的动态条带。"""
        del key
        cls._draw(canvas, snapshot or {})


def create_fps_simple_style():
    """创建 FPS 监控简约样式实例。"""
    return FpsSimpleStyle()


register_style(FpsSimpleStyle.name, create_fps_simple_style)
