"""提供兼容原 Canvas 接口的固件 C 加速适配器。"""

from canvas import Canvas as PythonCanvas

try:
    import fn_canvas as _native_canvas
except ImportError:
    _native_canvas = None


NATIVE_CANVAS_API_VERSION = 6
NATIVE_CANVAS_METHODS = (
    "clear", "pixel", "fill_rect", "line", "fill_polygon", "draw_columns",
    "draw_rect", "draw_grid", "draw_polyline", "draw_line_chart",
    "draw_text", "draw_commands",
)

_FONT_KINDS = {
    "native": 0,
    "screen_2inch": 1,
    "screen_2inch_compact": 2,
}


def native_canvas_supported():
    """检查当前 UF2 是否完整提供兼容版本的 Canvas C 接口。"""
    if _native_canvas is None:
        return False
    try:
        return (
            _native_canvas.api_version() == NATIVE_CANVAS_API_VERSION
            and all(
                callable(getattr(_native_canvas, method_name, None))
                for method_name in NATIVE_CANVAS_METHODS
            )
        )
    except (AttributeError, TypeError, ValueError):
        return False


class CanvasC(PythonCanvas):
    """通过适配器模式将原 Canvas 图元操作转发给固件 C 模块。"""

    native_accelerated = True

    def __init__(self, width, height):
        """创建与原 Canvas 具有相同缓冲区和缓存结构的加速画布。"""
        if not native_canvas_supported():
            raise RuntimeError("当前 UF2 不支持兼容版本的 Canvas C 后端")
        super().__init__(width, height)

    def clear(self, color=0):
        """通过 C 后端使用指定 RGB565 颜色清空当前视口。"""
        _native_canvas.clear(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, color,
        )

    def pixel(self, x, y, color):
        """通过 C 后端绘制经过视口裁剪的单个像素。"""
        _native_canvas.pixel(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, x, y, color,
        )

    def fill_rect(self, x, y, width, height, color):
        """通过 C 后端绘制经过视口裁剪的实心矩形。"""
        _native_canvas.fill_rect(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, x, y, width, height, color,
        )

    def line(self, x0, y0, x1, y1, color):
        """通过 C 后端绘制整数 Bresenham 线段。"""
        _native_canvas.line(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, x0, y0, x1, y1, color,
        )

    def text(self, x, y, value, color, scale=1):
        """通过单次 C 调用绘制放大文字或自定义字体文字。"""
        if self._font_name == "native" and scale == 1:
            super().text(x, y, value, color, scale)
            return
        _native_canvas.draw_text(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y,
            self._font, _FONT_KINDS.get(self._font_name, 0),
            x, y, str(value), color, scale,
        )

    def draw_commands(self, commands):
        """通过单次 C 调用执行矩形填充、线段和边框命令。"""
        if commands:
            _native_canvas.draw_commands(
                self.buffer, self.width, self.height,
                self.origin_x, self.origin_y, commands,
            )

    def fill_polygon(self, points, color):
        """通过 C 扫描线后端填充多边形并返回是否成功。"""
        if len(points) >= 2:
            baseline_y = points[0][1]
            if all(point[1] == baseline_y for point in points[1:]):
                # C 扫描线不会填充零面积多边形，改为保留一像素 X 轴基线。
                left = min(point[0] for point in points)
                right = max(point[0] for point in points)
                self.line(left, baseline_y, right, baseline_y, color)
                return True
        return _native_canvas.fill_polygon(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, points, color,
        )

    def draw_columns(self, columns, bottom=None):
        """通过 C 后端批量绘制历史图采样列。"""
        if columns:
            _native_canvas.draw_columns(
                self.buffer, self.width, self.height,
                self.origin_x, self.origin_y, columns, bottom,
            )

    def draw_line_chart(self, definition, values):
        """将图表定义和原始数据一次性交给 C 组件完成绘制。"""
        _native_canvas.draw_line_chart(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y,
            int(definition.get("x", 0)),
            int(definition.get("y", 0)),
            int(definition.get("width", 0)),
            int(definition.get("height", 0)),
            values,
            definition.get("maximum", 0),
            int(definition.get("color", 0xFFFF)),
            bool(definition.get("filled", False)),
            definition.get("regions") or None,
            int(definition.get("grid_step_x", 0)),
            int(definition.get("grid_step_y", 0)),
            int(definition.get("grid_color", 0)),
            definition.get("color_callback"),
            definition.get("color_cache_step", 1),
        )

    def draw_grid(self, x, y, width, height, step_x, step_y, color):
        """通过单次 C 调用绘制规则点阵网格。"""
        _native_canvas.draw_grid(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y,
            x, y, width, height, step_x, step_y, color,
        )

    def draw_rect(self, x, y, width, height, color):
        """通过单次 C 调用绘制一像素矩形边框。"""
        _native_canvas.draw_rect(
            self.buffer, self.width, self.height,
            self.origin_x, self.origin_y, x, y, width, height, color,
        )

    def draw_polyline(self, points, color):
        """通过单次 C 调用连接已完成缩放和取整的折线坐标。"""
        if points:
            _native_canvas.draw_polyline(
                self.buffer, self.width, self.height,
                self.origin_x, self.origin_y, points, color,
            )
