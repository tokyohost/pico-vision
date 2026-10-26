"""为内置样式的中文文本选择现有十二像素字库，保持英文默认字体。"""

try:
    import fn_canvas
except ImportError:
    fn_canvas = None

# 较早 SDK 仍提供文泉驿字库；不能因国际化强制升级底层 SDK。
CHINESE_FONT = "zlabs_pixel_12px" if (
    fn_canvas is not None and callable(getattr(fn_canvas, "api_version", None))
    and fn_canvas.api_version() >= 10
) else "wqy_8x16"


def _font(value, font_name):
    """仅在未指定字体且包含汉字时选择紧凑中文字库。"""
    if font_name is None and any("\u3400" <= char <= "\u9fff" for char in str(value)):
        return CHINESE_FONT
    return font_name


def draw_text(canvas, x, y, value, color, scale=1, font_name=None):
    """按文本字形选择字体，保留调用方显式字体及缩放参数。"""
    font = _font(value, font_name)
    if font is None:
        canvas.text(x, y, value, color, scale)
    else:
        canvas.text(x, y, value, color, scale, font_name=font)


def text_width(canvas, value, scale=1, font_name=None):
    """使用与实际绘制相同的字体测量，避免居中或裁剪计算偏移。"""
    font = _font(value, font_name)
    if font is None:
        return canvas.text_width(value, scale)
    return canvas.text_width(value, scale, font_name=font)


def fit_text(canvas, value, width, scale=1, font_name=None):
    """按实际字宽裁剪固定区域文案，不按字符数量猜测显示宽度。"""
    value = str(value)
    while value and text_width(canvas, value, scale, font_name) > width:
        value = value[:-1]
    return value
