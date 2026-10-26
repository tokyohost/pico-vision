"""使用现有画布绘制自适应中文列表菜单。"""

from i18n import t

from config import BLACK, BLUE, GRAY, WHITE, YELLOW

FONT = "wqy_8x16"


def wrap_text(canvas, text, width):
    """按实际字体宽度逐字换行，保留空格和全部正文字符。"""
    lines = []
    for paragraph in str(text).split("\n"):
        line = ""
        for character in paragraph:
            if line and canvas.text_width(line + character, font_name=FONT) > width:
                lines.append(line)
                line = ""
            line += character
        lines.append(line)
    return lines or [""]


def _fit(canvas, text, width):
    """按实际字体宽度截断过长文本。"""
    if canvas.text_width(text, font_name=FONT) <= width:
        return text
    while text and canvas.text_width(text + "...", font_name=FONT) > width:
        text = text[:-1]
    return text + "..."


def draw_menu(canvas, view, width, height):
    """按画布大小分页，保证选中项始终位于可视区域。"""
    canvas.clear(BLACK)
    canvas.fill_rect(0, 0, width, 30, BLUE)
    canvas.text(8, 7, _fit(canvas, view["title"], width - 16), WHITE, font_name=FONT)
    rows = max(1, (height - 86) // 26)
    selected = view["selected"]
    items = view["items"]
    start = (selected // rows) * rows
    for index in range(start, min(start + rows, len(items))):
        value, label = items[index]
        y = 34 + (index - start) * 26
        if index == selected:
            canvas.fill_rect(4, y, width - 8, 24, BLUE)
        marker = "" if view.get("type") == "detail" else (
            "* " if value is not None and value == view["current"] else "  ")
        canvas.text(8, y + 4, _fit(canvas, marker + label, width - 16), WHITE, font_name=FONT)
    status = view.get("message") or "{}/{}".format(selected + 1, len(items))
    canvas.text(8, height - 44, _fit(canvas, status, width - 16), YELLOW, font_name=FONT)
    canvas.text(8, height - 22, _fit(canvas, t('menu.help'), width - 16), GRAY, font_name=FONT)
