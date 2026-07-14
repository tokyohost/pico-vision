"""Pico LCD 样式开发标准模板 / Standard Pico LCD style template.

使用说明 / Usage:
1. 将本文件复制到 Pico 固件的 ``styles/style_<name>.py``。
   Copy this file to ``styles/style_<name>.py`` in the Pico firmware.
2. 修改 ``name``、``zh_name``、布局坐标和绘制逻辑；name 仅允许小写字母、数字和下划线。
   Change ``name``, ``zh_name``, layout coordinates and drawing logic. The name may
   contain only lower-case letters, digits and underscores.
3. 保留文件末尾的 ``register_style`` 调用，并把样式名加入监控端可选样式列表。
   Keep the final ``register_style`` call and expose the name in the monitor client.

本模板既是可运行的最小样式，也是 C 加速 Canvas 接口的调用参考。CanvasC 与 Python
Canvas 具有相同的公开接口，因此样式层不应直接导入 ``fn_canvas``，也不应判断当前后端。
This is both a runnable minimal style and a reference for the C-accelerated Canvas API.
CanvasC and the Python Canvas share the same public API; styles must not import
``fn_canvas`` directly or branch on the active backend.
"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, WHITE, YELLOW
from canvas import DRAW_COMMAND_FILL_RECT, DRAW_COMMAND_LINE, DRAW_COMMAND_RECT
from styles.style_plugins import register_style


class TemplateStyle:
    """封装示例界面的布局、增量刷新和 C 加速绘制示例。 / Define layout, dirty refresh and accelerated drawing examples."""

    # 元数据必须写成简单字符串常量，样式目录扫描器会直接读取这三行。
    # Metadata must be plain string constants because the catalog reads these lines directly.
    name = "template"
    zh_name = "标准模板"
    type = "custom"

    # 竖屏默认 240 x 320；横屏改为 width=320、height=240、landscape=True。
    # Portrait defaults to 240 x 320. For landscape use 320 x 240 and landscape=True.
    width = 240
    height = 320
    landscape = False
    # 本属性只定义该样式的默认字体，单次 text() 仍可通过 font_name 临时覆盖。
    font_name = "native"

    def __init__(self):
        """初始化有明确上限、可跨帧复用的缓存。 / Initialize bounded caches reusable across frames."""
        self._prepared_snapshot = None
        self._prepared_text = {}
        self._command_cache = {}

    def prepare_frame(self, snapshot):
        """在渲染计时前统一格式化本帧文本，减少重复转换。 / Format frame text once before timed rendering."""
        snapshot = snapshot or {}
        cpu = snapshot.get("cpu", {})
        network = snapshot.get("network", {})
        timestamp = str(snapshot.get("timestamp", ""))
        self._prepared_text = {
            "host": str(snapshot.get("host", "WAITING"))[:18],
            "cpu": "{}%".format(int(self._number(cpu.get("percent")))),
            "clock": timestamp[11:19] if len(timestamp) >= 19 else "--:--:--",
            "network": "ONLINE" if network.get("online") else "OFFLINE",
        }
        self._prepared_snapshot = snapshot

    def _ensure_prepared(self, snapshot):
        """确保测试或外部直接绘制时也已准备本帧数据。 / Ensure frame data exists for direct/test rendering."""
        if self._prepared_snapshot is not snapshot:
            self.prepare_frame(snapshot)

    @staticmethod
    def create_dirty_regions():
        """声明全部动态区域，元组格式为 key、x、y、宽、高。 / Declare every dynamic region as key, x, y, width, height."""
        # 区域应覆盖旧内容的最大范围；渲染器在 draw_dirty 前会清空整个区域。
        # Cover the maximum old-content bounds; the renderer clears the region first.
        return [
            ("header", 8, 8, 224, 20),
            ("cpu_value", 8, 46, 88, 20),
            # 单个脏矩形不得超过 240×40 条带画布容量，图表拆成上下两块刷新。
            # A dirty region must fit the 240×40 strip canvas, so split the chart vertically.
            ("cpu_history_top", 8, 72, 224, 38),
            ("cpu_history_bottom", 8, 110, 224, 38),
            ("network", 8, 166, 224, 22),
            ("footer", 8, 292, 224, 18),
        ]

    @classmethod
    def select_dirty_regions(cls, previous, current):
        """按字段差异返回实际需要更新的区域。 / Return only regions affected by field-level changes."""
        previous = previous or {}
        current = current or {}
        region_map = {region[0]: region for region in cls.create_dirty_regions()}
        selected = []
        previous_cpu = previous.get("cpu", {})
        current_cpu = current.get("cpu", {})

        if previous.get("host") != current.get("host"):
            selected.append(region_map["header"])
        if previous_cpu.get("percent") != current_cpu.get("percent"):
            selected.append(region_map["cpu_value"])
        if previous_cpu.get("history") != current_cpu.get("history"):
            selected.append(region_map["cpu_history_top"])
            selected.append(region_map["cpu_history_bottom"])
        if previous.get("network") != current.get("network"):
            selected.append(region_map["network"])
        if (previous.get("timestamp"), previous.get("uptime_seconds")) != (
            current.get("timestamp"), current.get("uptime_seconds")
        ):
            selected.append(region_map["footer"])
        return selected

    @staticmethod
    def _number(value, default=0):
        """将不可信指标安全转换为浮点数。 / Safely convert an untrusted metric to float."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _visible(canvas, top, bottom):
        """判断完整屏幕坐标区间是否与当前条带画布相交。 / Test whether screen coordinates intersect the current strip."""
        return top < canvas.origin_y + canvas.height and bottom > canvas.origin_y

    def _draw_frame(self, canvas, x, y, width, height, color):
        """用单次 C 调用绘制矩形边框。 / Draw a rectangle border with one C call."""
        # C 优化接口示例 1：不要用四次 line() 手工拼边框。
        # C API example 1: avoid assembling a border with four line() calls.
        canvas.draw_rect(x, y, width, height, color, thickness=1)

    def _draw_progress(self, canvas, x, y, width, height, percent, color):
        """批量提交进度条命令并复用命令列表。 / Batch progress-bar commands and reuse the command list."""
        value = max(0, min(100, self._number(percent)))
        cache_key = (x, y, width, height, color)
        commands = self._command_cache.get(cache_key)
        if commands is None:
            # C 优化接口示例 2：每条命令均为 [操作, x, y, 参数A, 参数B, 颜色]。
            # C API example 2: each command is [operation, x, y, valueA, valueB, color].
            commands = [
                [DRAW_COMMAND_FILL_RECT, x, y, width, height, DARK],
                [DRAW_COMMAND_FILL_RECT, x + 1, y + 1, 0, height - 2, color],
                [DRAW_COMMAND_RECT, x, y, width, height, color],
            ]
            self._command_cache[cache_key] = commands
        commands[1][3] = int((width - 2) * value / 100)
        canvas.draw_commands(commands)

    @staticmethod
    def _draw_history(canvas, values):
        """一次提交图表定义与原始采样值，由后端完成缩放和绘制。 / Submit chart definition and raw samples in one call."""
        # C 优化接口示例 3：maximum=0 表示按数据自动取最大值；filled=True 绘制面积图。
        # C API example 3: maximum=0 enables auto scaling; filled=True draws an area chart.
        canvas.draw_line_chart({
            "x": 8,
            "y": 72,
            "width": 224,
            "height": 76,
            "maximum": 100,
            "color": BLUE,
            "filled": True,
            # regions 使用 (上限, 颜色)，值按顺序匹配第一个小于上限的区间。
            # regions contain (upper_limit, color); the first matching range wins.
            "regions": ((60, GREEN), (85, YELLOW), (101, BLUE)),
            "grid_step_x": 16,
            "grid_step_y": 12,
            "grid_color": GRAY,
        }, values or ())

    @staticmethod
    def _draw_additional_c_examples(canvas):
        """集中展示其余 C 接口；按需复制调用，不在默认布局执行。 / Show optional C APIs; copy as needed, not drawn by default."""
        # 规则点阵网格 / Regular dotted grid.
        canvas.draw_grid(8, 200, 96, 40, 8, 8, GRAY)

        # 已完成缩放的折线坐标 / Pre-scaled polyline points.
        canvas.draw_polyline(((8, 230), (24, 218), (40, 225)), GREEN)

        # 同色实心多边形 / Solid single-color polygon.
        canvas.fill_polygon(((120, 230), (136, 206), (152, 230)), YELLOW)

        # 每列可使用不同颜色；bottom 非 None 时填充到底边，否则只画采样点。
        # Each column may have a color. Set bottom to fill the area, or None for pixels.
        canvas.draw_columns(((168, 220, GREEN), (169, 216, YELLOW), (170, 210, BLUE)), 230)

        # 批量命令也支持线段；valueA/valueB 在此表示终点 x1/y1。
        # Batch commands also support lines; valueA/valueB are endpoint x1/y1 here.
        canvas.draw_commands(((DRAW_COMMAND_LINE, 184, 210, 224, 230, WHITE),))

    def _draw_header(self, canvas):
        """绘制主机名标题。 / Draw the host-name header."""
        canvas.text(8, 8, self._prepared_text["host"], WHITE, 2)

    def _draw_cpu_value(self, canvas, snapshot):
        """绘制 CPU 当前值和批量进度条。 / Draw the current CPU value and batched progress bar."""
        cpu = snapshot.get("cpu", {})
        canvas.text(8, 46, self._prepared_text["cpu"], BLUE, 2)
        self._draw_progress(canvas, 72, 49, 160, 12, cpu.get("percent"), BLUE)

    def _draw_network(self, canvas):
        """绘制网络状态。 / Draw network state."""
        online = self._prepared_text["network"] == "ONLINE"
        canvas.text(8, 166, self._prepared_text["network"], GREEN if online else YELLOW)

    def _draw_footer(self, canvas):
        """绘制时钟页脚。 / Draw the clock footer."""
        canvas.text(8, 292, self._prepared_text["clock"], GRAY)

    def draw_visible(self, canvas, snapshot):
        """首次显示或完整重绘时，绘制与当前条带相交的全部内容。 / Draw all content intersecting the current strip."""
        snapshot = snapshot or {}
        self._ensure_prepared(snapshot)
        canvas.clear(BLACK)
        if self._visible(canvas, 0, 32):
            self._draw_frame(canvas, 2, 2, 236, 30, BLUE)
            self._draw_header(canvas)
        if self._visible(canvas, 38, 68):
            self._draw_cpu_value(canvas, snapshot)
        if self._visible(canvas, 72, 148):
            self._draw_history(canvas, snapshot.get("cpu", {}).get("history", ()))
        if self._visible(canvas, 160, 192):
            self._draw_network(canvas)
        if self._visible(canvas, 286, 318):
            self._draw_footer(canvas)

    def draw_dirty(self, canvas, key, snapshot):
        """重绘一个已由渲染器裁剪并清空的动态区域。 / Redraw one renderer-clipped and cleared dirty region."""
        snapshot = snapshot or {}
        self._ensure_prepared(snapshot)
        canvas.clear(BLACK)
        if key == "header":
            self._draw_header(canvas)
        elif key == "cpu_value":
            self._draw_cpu_value(canvas, snapshot)
        elif key in ("cpu_history_top", "cpu_history_bottom"):
            self._draw_history(canvas, snapshot.get("cpu", {}).get("history", ()))
        elif key == "network":
            self._draw_network(canvas)
        elif key == "footer":
            self._draw_footer(canvas)


def create_template_style():
    """创建标准模板样式实例，供插件注册表按名称加载。 / Create the style instance for registry loading."""
    return TemplateStyle()


# 模块导入时完成注册；复制模板后应同步修改工厂函数和类名，便于维护。
# Register on import. Rename the factory and class after copying for maintainability.
register_style(TemplateStyle.name, create_template_style)
