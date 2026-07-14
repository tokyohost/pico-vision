"""验证 ESP32-S3 启动页不会加载慢速 Fusion Pixel 字库。"""


import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

import dashboard as dashboard_module


class FakeLcd:
    """提供启动页渲染器初始化需要的 LCD 档案。"""

    def __init__(self):
        """创建二百四十乘三百二十的模拟面板。"""
        self.panel_profile = SimpleNamespace(width=240, height=320)
        self.landscape = None

    def set_landscape(self, landscape):
        """记录渲染器选择的横竖屏方向。"""
        self.landscape = bool(landscape)


class Esp32StyleFontTest(unittest.TestCase):
    """确认 ESP32-S3 遵循各样式声明的默认字体。"""

    def test_boot_style_keeps_native_font(self):
        """启动页应使用固件原生字体以避免旧固件闪存查找卡顿。"""
        renderer = dashboard_module.DashboardRenderer(
            FakeLcd(),
            style_name="boot",
        )

        self.assertEqual("native", renderer.canvas._font_name)

    def test_compact_style_keeps_pico_font_on_esp32(self):
        """ESP32-S3 不应覆盖紧凑样式声明的自定义字体。"""
        renderer = dashboard_module.DashboardRenderer(
            FakeLcd(),
            style_name="simple",
        )

        self.assertEqual("screen_2inch_compact", renderer.canvas._font_name)


if __name__ == "__main__":
    unittest.main()
