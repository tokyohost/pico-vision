"""提供文泉驿8*16清晰点阵字体测试样式。"""

from config import BLACK, BLUE, DARK, GRAY, GREEN, PURPLE, WHITE, YELLOW
from styles.style_plugins import register_style


WQY_FONT_NAME = "wqy_8x16"
SCREEN_WIDTH = 240
SCREEN_HEIGHT = 320
STRIP_HEIGHT = 40


class Wqy8x16TestStyle:
    """使用一位点阵和整数倍缩放展示文泉驿中英文字形。"""

    name = "wqy_8x16_test"
    zh_name = "文泉驿清晰点阵测试"
    type = "builtin"
    idle = False
    width = SCREEN_WIDTH
    height = SCREEN_HEIGHT
    landscape = False
    font_name = WQY_FONT_NAME

    @staticmethod
    def create_dirty_regions():
        """按四十像素高度创建适配条带画布的全屏刷新区域。"""
        return [
            (
                "wqy_8x16_strip_{}".format(index),
                0,
                index * STRIP_HEIGHT,
                SCREEN_WIDTH,
                STRIP_HEIGHT,
            )
            for index in range(SCREEN_HEIGHT // STRIP_HEIGHT)
        ]

    @staticmethod
    def _center_text(canvas, y, value, color, scale=1):
        """使用文泉驿点阵字体在屏幕水平方向居中绘制文字。"""
        width = canvas.text_width(value, scale, font_name=WQY_FONT_NAME)
        canvas.text(
            max(0, (SCREEN_WIDTH - width) // 2),
            y,
            value,
            color,
            scale,
            font_name=WQY_FONT_NAME,
        )

    @classmethod
    def _draw(cls, canvas):
        """绘制只使用黑白点阵字形和整数倍缩放的完整测试页。"""
        canvas.clear(BLACK)

        canvas.fill_rect(0, 0, SCREEN_WIDTH, 54, BLUE)
        cls._center_text(canvas, 7, "文泉驿点阵", WHITE, 2)
        cls._center_text(canvas, 36, "清晰字体显示测试", WHITE)

        canvas.fill_rect(8, 64, 224, 72, DARK)
        canvas.text(16, 72, "常用中文", YELLOW, font_name=WQY_FONT_NAME)
        cls._center_text(canvas, 94, "你好，世界！", WHITE)
        cls._center_text(canvas, 116, "系统运行正常", GREEN)

        canvas.fill_rect(8, 146, 224, 76, DARK)
        canvas.text(16, 154, "数字与英文", BLUE, font_name=WQY_FONT_NAME)
        cls._center_text(canvas, 177, "CPU 88%  RAM 64%", WHITE)
        cls._center_text(canvas, 199, "温度 36℃  帧率 120", GREEN)

        canvas.fill_rect(8, 232, 224, 78, DARK)
        canvas.text(16, 240, "笔画与标点", PURPLE, font_name=WQY_FONT_NAME)
        cls._center_text(canvas, 262, "横竖撇捺 点阵清晰", WHITE)
        cls._center_text(canvas, 288, "，。！？：；（）【】", GRAY)

    @classmethod
    def draw_visible(cls, canvas, snapshot):
        """绘制当前可见条带内的文泉驿字体测试内容。"""
        del snapshot
        cls._draw(canvas)

    @classmethod
    def draw_dirty(cls, canvas, key, snapshot):
        """重绘指定条带内的文泉驿字体测试内容。"""
        del key, snapshot
        cls._draw(canvas)


def create_wqy_8x16_test_style():
    """创建文泉驿八乘十六清晰点阵字体测试样式。"""
    return Wqy8x16TestStyle()


register_style(Wqy8x16TestStyle.name, create_wqy_8x16_test_style)
