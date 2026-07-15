"""提供 Fusion Pixel 中文字体显示测试样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, WHITE, YELLOW
from styles.style_plugins import register_style


FUSION_FONT_NAME = "fusion_pixel_8x16"
COMPACT_FONT_NAME = "screen_2inch_compact"
SCREEN_WIDTH = 240
SCREEN_HEIGHT = 320
STRIP_HEIGHT = 40


class FusionPixelTestStyle:
    """分区展示 Fusion Pixel 的中文、英文、数字和标点字形。"""

    name = "fusion_pixel_test"
    zh_name = "融合像素中文测试"
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
                "fusion_pixel_strip_{}".format(index),
                0,
                index * STRIP_HEIGHT,
                SCREEN_WIDTH,
                STRIP_HEIGHT,
            )
            for index in range(SCREEN_HEIGHT // STRIP_HEIGHT)
        ]

    @staticmethod
    def _center_text(canvas, y, value, color, scale=1, font_name=FUSION_FONT_NAME):
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
        cls._center_text(canvas, 7, "融合像素", WHITE, 2)
        cls._center_text(canvas, 36, "中文字体显示测试", WHITE)

        canvas.fill_rect(8, 64, 224, 72, DARK)
        canvas.text(16, 72, "常用中文", YELLOW, font_name=FUSION_FONT_NAME)
        cls._center_text(canvas, 94, "你好，世界！", WHITE)
        cls._center_text(canvas, 116, "系统运行正常", GREEN)

        canvas.fill_rect(8, 146, 224, 76, DARK)
        canvas.text(16, 154, "数字与英文", BLUE, font_name=FUSION_FONT_NAME)
        cls._center_text(canvas, 177, "CPU 88%  内存 64%", WHITE)
        cls._center_text(canvas, 199, "温度 36℃  帧率 120", GREEN)

        canvas.fill_rect(8, 232, 224, 78, DARK)
        canvas.text(16, 240, "标点符号", PURPLE, font_name=FUSION_FONT_NAME)
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


def create_fusion_pixel_test_style():
    """创建 Fusion Pixel 中文字体测试样式。"""
    return FusionPixelTestStyle()


register_style(FusionPixelTestStyle.name, create_fusion_pixel_test_style)
