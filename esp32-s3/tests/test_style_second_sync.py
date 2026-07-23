"""验证 ESP32-S3 Style 独立控制原生可见帧整秒同步。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ESP32_S3_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_S3_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_S3_ROOT))

from dashboard import DashboardRenderer  # noqa: E402


class RecordingLcd:
    """记录 Style 切换时下发的原生整秒同步策略。"""

    def __init__(self):
        """创建模拟面板和空策略记录。"""
        self.panel_profile = SimpleNamespace(width=320, height=320)
        self.sync_policies = []

    def set_landscape(self, landscape):
        """接受 Style 声明的横竖屏方向。"""
        self.landscape = bool(landscape)

    def configure_canvas(self, width, height):
        """接受完整画布尺寸并模拟配置成功。"""
        self.canvas_size = (int(width), int(height))
        return True

    def set_visible_frame_second_sync(self, enabled):
        """记录当前 Style 下发的整秒同步布尔值。"""
        enabled = bool(enabled)
        changed = not self.sync_policies or self.sync_policies[-1] != enabled
        self.sync_policies.append(enabled)
        return changed


class StyleSecondSyncTest(unittest.TestCase):
    """覆盖启动、监控和高频 Style 的独立同步策略。"""

    def test_style_switch_updates_native_second_sync_policy(self):
        """确认切换 Style 时立即向 LCD 后端下发各自声明的策略。"""
        lcd = RecordingLcd()
        renderer = DashboardRenderer(lcd, style_name="boot")

        self.assertTrue(lcd.sync_policies)
        self.assertTrue(all(policy is False for policy in lcd.sync_policies))
        self.assertTrue(renderer.set_style("idle"))
        self.assertEqual(lcd.sync_policies[-1], True)
        self.assertTrue(renderer.set_style("fps_simple"))
        self.assertEqual(lcd.sync_policies[-1], False)


if __name__ == "__main__":
    unittest.main()
