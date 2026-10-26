"""按固件字宽和行高验证双语样式的固定坐标布局。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import font_builtin
import i18n
import screen_text
from canvas import Canvas
from styles.style_plugins import create_style


class RecordingCanvas(Canvas):
    """复用真实字体定义，仅记录文字边界供排版断言使用。"""

    def __init__(self, width, height):
        """创建与样式尺寸一致的画布和文字区域记录。"""
        super().__init__(width, height)
        self.texts = []

    def draw_grid(self, *args, **kwargs):
        """布局测试无需绘制不含文本的网格背景。"""

    def draw_line_chart(self, *args, **kwargs):
        """布局测试无需绘制不含文本的折线区域。"""

    def text(self, x, y, value, color, scale=1, font_name=None):
        """记录使用实际字体定义测得的文字矩形。"""
        previous = self._select_text_font(font_name)
        width, height = self.text_width(value, scale), self._font_height() * scale
        self._restore_text_font(previous)
        self.texts.append((x, y, width, height, str(value)))


class I18nLayoutTest(unittest.TestCase):
    """验证系统页双语布局，主题不随语言切换。"""

    def test_builtin_text_regions_fit_without_overlap(self):
        """空数据和多磁盘数据均不应让关键文字出屏或互相遮挡。"""
        def measure(kind, text, scale):
            """模拟固件字体编号三、四、五的半角与全角步进。"""
            half = 6 if kind == 5 else 8
            return sum(half if ord(char) < 128 else half * 2 for char in text) * scale

        snapshots = ({}, {
            "timestamp": "2026-10-24 12:34:56", "host": "PC", "uptime_seconds": 3600,
            "network": {"ip": "192.168.1.2"}, "display": {"network_unit": "MB"},
            "disks": [{"name": "DISK" + str(index), "health": index % 6,
                       "temperature_c": 40, "used_bytes": 128000000000,
                       "total_bytes": 256000000000, "percent": 100 if index % 2 else 50}
                      for index in range(15)],
            "qbittorrent": {"enabled": True, "connection_status": "disconnected",
                            "torrents": {"all": 12345, "seeding": 10000, "active": 2345}},
        })
        names = [path.stem[6:] for path in Path(__file__).resolve().parents[1].glob("styles/style_*.py")
                 if "test" not in path.stem and path.stem != "style_plugins"]
        theme_texts = {}
        for version, font in ((9, "wqy_8x16"), (10, "zlabs_pixel_12px")):
            native = SimpleNamespace(api_version=lambda: version, text_width=measure, font_glyph=lambda *args: ())
            for language in ("zh-CN", "en-US"):
                with mock.patch.object(font_builtin, "_native_canvas", native), \
                        mock.patch.object(screen_text, "CHINESE_FONT", font), \
                        mock.patch.object(i18n, "_locale", language):
                    for name in names:
                        for snapshot in snapshots:
                            with self.subTest(version=version, language=language, style=name, populated=bool(snapshot)):
                                style = create_style(name)
                                canvas = RecordingCanvas(getattr(style, "width", 240), getattr(style, "height", 320))
                                canvas.set_font(getattr(style, "font_name", "native"))
                                style.draw_visible(canvas, snapshot)
                                if name != "boot":
                                    key = (version, name, bool(snapshot))
                                    if language == "zh-CN":
                                        theme_texts[key] = canvas.texts
                                    else:
                                        self.assertEqual(theme_texts[key], canvas.texts)
                                # 待机页原有灰色分钟水印是有意叠绘，不属于正文遮挡。
                                texts = [item for item in canvas.texts if not (name == "idle" and item[1] == 34)]
                                for index, rect in enumerate(texts):
                                    x, y, width, height, text = rect
                                    self.assertGreaterEqual(x, 0, rect)
                                    self.assertGreaterEqual(y, 0, rect)
                                    self.assertLessEqual(x + width, canvas.width, rect)
                                    self.assertLessEqual(y + height, canvas.height, rect)
                                    for other in texts[index + 1:]:
                                        overlap = (x < other[0] + other[2] and other[0] < x + width
                                                   and y < other[1] + other[3] and other[1] < y + height)
                                        self.assertFalse(overlap, (rect, other))


if __name__ == "__main__":
    unittest.main()
