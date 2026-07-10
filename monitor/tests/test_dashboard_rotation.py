"""验证 Pico 屏幕旋转过程不会额外申请整条清屏缓冲。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from dashboard import DashboardRenderer  # noqa: E402


class RecordingCanvas:
    """提供可复用缓冲，并记录旋转清屏使用的画布视口。"""

    def __init__(self, width, strip_height):
        """创建填入非黑色像素的固定容量条带缓冲。"""
        self.buffer = bytearray([0xFF]) * (width * strip_height * 2)
        self.views = []

    def set_view(self, x, y, width, height):
        """记录固件清屏时选择的条带视口。"""
        self.views.append((x, y, width, height))

    def clear(self, color):
        """在原缓冲区内模拟画布黑色填充。"""
        self.buffer[:] = bytes((color >> 8, color & 0xFF)) * (
            len(self.buffer) // 2
        )


class RecordingLcd:
    """记录显示开关、旋转角度和 LCD 区域写入。"""

    def __init__(self):
        """初始化正常方向及调用记录。"""
        self._rotation = 0
        self.enabled = []
        self.regions = []

    def rotation(self):
        """返回当前模拟屏幕方向。"""
        return self._rotation

    def set_display_enabled(self, enabled):
        """记录旋转前后的显示开关状态。"""
        self.enabled.append(enabled)

    def set_rotation(self, rotation):
        """保存新的模拟屏幕方向。"""
        self._rotation = rotation
        return True

    def show_region(self, x, y, width, height, pixels):
        """记录区域参数及像素视图引用的底层缓冲。"""
        self.regions.append((x, y, width, height, pixels.obj, len(pixels)))


class DashboardRotationTest(unittest.TestCase):
    """覆盖屏幕旋转清屏的低内存实现。"""

    def test_rotation_reuses_canvas_strip_buffer(self):
        """旋转一百八十度应复用画布缓冲完成全部条带清屏。"""
        renderer = DashboardRenderer.__new__(DashboardRenderer)
        renderer._width = 240
        renderer._height = 320
        renderer._initialized = True
        renderer.canvas = RecordingCanvas(240, 40)
        renderer.lcd = RecordingLcd()

        changed = renderer.set_rotation(180)

        self.assertTrue(changed)
        self.assertEqual(renderer.lcd.rotation(), 180)
        self.assertEqual(renderer.lcd.enabled, [False, True])
        self.assertFalse(renderer._initialized)
        self.assertEqual(len(renderer.lcd.regions), 8)
        self.assertEqual(
            renderer.canvas.views,
            [(0, y, 240, 40) for y in range(0, 320, 40)],
        )
        for _x, _y, _width, _height, buffer, byte_count in renderer.lcd.regions:
            self.assertIs(buffer, renderer.canvas.buffer)
            self.assertEqual(byte_count, 240 * 40 * 2)
        self.assertFalse(any(renderer.canvas.buffer))


if __name__ == "__main__":
    unittest.main()
