# Copyright (c) 2026 xuehui_li
#
# Licensed under the Custom Non-Commercial Copyleft License.
# Commercial use is prohibited without prior written permission.

"""实现用于验证 FPS 采集和稳帧表现的横屏测试样式。"""


from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, RED, WHITE, YELLOW
from styles.style_plugins import register_style


class FpsTestStyle:
    """绘制实时 FPS、采集状态和最近历史稳帧曲线。"""

    name = "fpstest"
    zh_name = "FPS 稳帧测试"
    type = "builtin"
    width = 320
    height = 240
    landscape = True
    font_name = "screen_2inch_compact"

    @staticmethod
    def create_dirty_regions():
        """按画布容量返回覆盖整个测试页的六个刷新条带。"""
        return [
            ("fps_strip_{}".format(index), 0, index * 40, 320, 40)
            for index in range(6)
        ]

    @staticmethod
    def select_dirty_regions(previous, current):
        """仅在 FPS 数据或时间发生变化时刷新测试页。"""
        if previous.get("fps") != current.get("fps") or previous.get("timestamp") != current.get("timestamp"):
            return FpsTestStyle.create_dirty_regions()
        return []

    @staticmethod
    def _number(value, default=0.0):
        """安全地将快照字段转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @classmethod
    def _valid_history(cls, fps):
        """返回剔除无效值后的最近 FPS 历史数据。"""
        values = []
        for value in (fps.get("history") or ()):
            number = cls._number(value, -1)
            if number >= 0:
                values.append(number)
        return values[-24:]

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断纵向区域是否与当前条带画布相交。"""
        origin = getattr(canvas, "origin_y", 0)
        height = getattr(canvas, "height", 240)
        return origin < bottom and origin + height > top

    @staticmethod
    def _frame(canvas, x, y, width, height, color):
        """绘制轻量矩形边框。"""
        canvas.fill_rect(x, y, width, 1, color)
        canvas.fill_rect(x, y + height - 1, width, 1, color)
        canvas.fill_rect(x, y, 1, height, color)
        canvas.fill_rect(x + width - 1, y, 1, height, color)

    @classmethod
    def _statistics(cls, fps):
        """计算历史 FPS 的均值、极值、波动范围与稳定度。"""
        values = cls._valid_history(fps)
        active_values = [value for value in values if value > 0]
        if not active_values:
            return values, 0.0, 0.0, 0.0, 0.0, 0
        average = sum(active_values) / len(active_values)
        minimum = min(active_values)
        maximum = max(active_values)
        spread = maximum - minimum
        deviation = sum(abs(value - average) for value in active_values) / len(active_values)
        stability = max(0, min(100, int(100 - deviation * 100 / max(1, average))))
        return values, average, minimum, maximum, spread, stability

    @staticmethod
    def _status(fps):
        """根据采集结果生成状态文本和状态颜色。"""
        if fps.get("value") is None:
            return "NO DATA", RED
        source = str(fps.get("source") or "").upper()
        if source == "PRESENTMON_ETW":
            return "PRESENTMON", GREEN
        if source == "AMD_ADLX":
            return "AMD ADLX", YELLOW
        return source[:14] or "ACTIVE", BLUE

    @classmethod
    def _draw_history(cls, canvas, values, x, y, width, height):
        """绘制带网格、均值参考线和自适应纵轴的 FPS 曲线。"""
        cls._frame(canvas, x, y, width, height, GRAY)
        for ratio in (1, 2, 3):
            grid_y = y + ratio * height // 4
            canvas.line(x + 1, grid_y, x + width - 2, grid_y, DARK)
        if len(values) < 2:
            canvas.text(x + 8, y + height // 2 - 4, "WAITING FOR FPS HISTORY", GRAY, 1)
            return
        maximum = max(30.0, max(values) * 1.1)
        average = sum(values) / len(values)
        average_y = y + height - 2 - int(average * (height - 4) / maximum)
        canvas.line(x + 1, average_y, x + width - 2, average_y, YELLOW)
        previous = None
        for index, value in enumerate(values):
            point_x = x + 2 + int(index * (width - 5) / (len(values) - 1))
            point_y = y + height - 2 - int(max(0, value) * (height - 4) / maximum)
            point_y = max(y + 1, min(y + height - 2, point_y))
            if previous is not None:
                canvas.line(previous[0], previous[1], point_x, point_y, GREEN)
            canvas.fill_rect(point_x, point_y, 2, 2, WHITE)
            previous = (point_x, point_y)
        scale_text = "0-{} FPS".format(int(maximum))
        canvas.text(x + width - 5 - canvas.text_width(scale_text), y + 5, scale_text, GRAY, 1)

    @classmethod
    def _draw(cls, canvas, snapshot):
        """绘制完整 FPS 测试仪表盘。"""
        fps = snapshot.get("fps") or {}
        values, average, minimum, maximum, spread, stability = cls._statistics(fps)
        current = fps.get("value")
        status_text, status_color = cls._status(fps)

        canvas.clear(BLACK)
        canvas.text(8, 8, "FPS STABILITY TEST", BLUE, 1)
        canvas.text(310 - canvas.text_width(status_text), 8, status_text, status_color, 1)
        cls._frame(canvas, 6, 24, 116, 82, BLUE)
        canvas.text(14, 33, "REALTIME", GRAY, 1)
        value_text = "--" if current is None else "{:.1f}".format(cls._number(current))
        value_color = RED if current is None else GREEN
        canvas.text(14, 52, value_text, value_color, 3)
        canvas.text(92, 84, "FPS", WHITE, 1)

        cls._frame(canvas, 128, 24, 186, 82, PURPLE)
        canvas.text(137, 33, "STABILITY", GRAY, 1)
        canvas.text(137, 50, "{}%".format(stability), GREEN if stability >= 90 else YELLOW, 2)
        canvas.text(224, 34, "AVG {:5.1f}".format(average), WHITE, 1)
        canvas.text(224, 50, "MIN {:5.1f}".format(minimum), BLUE, 1)
        canvas.text(224, 66, "MAX {:5.1f}".format(maximum), GREEN, 1)
        canvas.text(224, 82, "RNG {:5.1f}".format(spread), YELLOW, 1)

        canvas.text(8, 113, "LAST 24 SECONDS", GRAY, 1)
        cls._draw_history(canvas, values, 6, 126, 308, 82)

        process_name = str(fps.get("process_name") or "--")
        process_id = fps.get("process_id")
        process_text = "{}  PID {}".format(process_name[:18], process_id if process_id is not None else "--")
        canvas.text(8, 218, process_text, WHITE, 1)
        timestamp = str(snapshot.get("timestamp") or "")
        clock = timestamp[11:19] if len(timestamp) >= 19 else "--:--:--"
        canvas.text(312 - canvas.text_width(clock), 218, clock, GRAY, 1)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制与当前条带相交的 FPS 测试页内容。"""
        cls._draw(canvas, snapshot or {})

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """重绘 FPS 测试页的动态区域。"""
        del key
        cls._draw(canvas, snapshot or {})


def create_fpstest_style():
    """创建 FPS 稳帧测试样式实例。"""
    return FpsTestStyle()


register_style(FpsTestStyle.name, create_fpstest_style)
