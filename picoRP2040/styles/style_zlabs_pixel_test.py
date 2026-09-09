"""提供 Z 工坊像素黑体十二像素字体显示测试样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, WHITE, YELLOW
from styles.style_plugins import register_style


ZLABS_FONT_NAME = "zlabs_pixel_12px"
COMPACT_FONT_NAME = "screen_2inch_compact"
SCREEN_WIDTH = 240
SCREEN_HEIGHT = 320
STRIP_HEIGHT = 40


class ZLabsPixelTestStyle:
    """分区展示 Z工坊像素黑体 12px 的中文、英文、数字和标点字形。"""

    name = "zlabs_pixel_test"
    zh_name = "Z工坊12px字体测试"
    type = "builtin"
    idle = False
    width = SCREEN_WIDTH
    height = SCREEN_HEIGHT
    landscape = False
    font_name = COMPACT_FONT_NAME

    @staticmethod
    def create_dirty_regions():
        """按四十像素高度创建可由条带画布承载的全屏刷新区域。"""
        return [
            (
                "zlabs_pixel_strip_{}".format(index),
                0,
                index * STRIP_HEIGHT,
                SCREEN_WIDTH,
                STRIP_HEIGHT,
            )
            for index in range(SCREEN_HEIGHT // STRIP_HEIGHT)
        ]

    @staticmethod
    def _center_text(canvas, y, value, color, scale=1, font_name=ZLABS_FONT_NAME):
        """使用指定字体在屏幕水平方向居中绘制文字。"""
        width = canvas.text_width(value, scale, font_name=font_name)
        canvas.text(
            max(0, (SCREEN_WIDTH - width) // 2),
            y,
            value,
            color,
            scale,
            font_name=font_name,
        )

    @classmethod
    def _draw(cls, canvas):
        """绘制完整字体测试页，画布视口负责裁剪当前条带。"""
        canvas.clear(BLACK)

        canvas.fill_rect(0, 0, SCREEN_WIDTH, 54, BLUE)
        cls._center_text(canvas, 7, "Z工坊像素", WHITE, 2)
        cls._center_text(canvas, 36, "Z Labs Pixel 12px", WHITE)

        canvas.fill_rect(8, 64, 224, 72, DARK)
        canvas.text(16, 72, "常用中文", YELLOW, font_name=ZLABS_FONT_NAME)
        cls._center_text(canvas, 94, "你好，世界！简体中文", WHITE)
        cls._center_text(canvas, 116, "系统运行正常 12px", GREEN)

        canvas.fill_rect(8, 146, 224, 76, DARK)
        canvas.text(16, 154, "数字与英文", BLUE, font_name=ZLABS_FONT_NAME)
        cls._center_text(canvas, 177, "CPU 88%  内存 64%", WHITE)
        cls._center_text(canvas, 199, "温度 36℃  帧率 120", GREEN)

        canvas.fill_rect(8, 232, 224, 78, DARK)
        canvas.text(16, 240, "标点符号", PURPLE, font_name=ZLABS_FONT_NAME)
        cls._center_text(canvas, 262, "，。！？：；（）【】", WHITE)
        cls._center_text(
            canvas,
            291,
            "COMPACT ABC 123",
            GRAY,
            font_name=COMPACT_FONT_NAME,
        )

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制当前可见条带内的字体测试内容。"""
        del snapshot
        cls._draw(canvas)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """重绘指定条带内的字体测试内容。"""
        del key, snapshot
        cls._draw(canvas)


def create_zlabs_pixel_test_style():
    """创建 Z工坊像素黑体 12px 中文字体测试样式。"""
    return ZLabsPixelTestStyle()


register_style(ZLabsPixelTestStyle.name, create_zlabs_pixel_test_style)
