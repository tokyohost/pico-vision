"""验证自定义样式画布容量异常的内置样式回退流程。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from main import Application


class RecordingProtocol:
    """记录固件发往 Monitor 的日志事件。"""

    def __init__(self):
        """初始化日志记录列表。"""
        self.messages = []

    def write(self, message):
        """保存一条固件日志。"""
        self.messages.append(bytes(message).decode("utf-8"))


class FailingRenderer:
    """模拟在刷新脏矩形时抛出画布容量异常的渲染器。"""

    def __init__(self, style_type="custom"):
        """保存样式类型及后续切换记录。"""
        self._style_type = style_type
        self.selected_style = None
        self.rendered_snapshot = None

    def update_pending(self, max_regions=8):
        """模拟渲染阶段的脏矩形容量错误。"""
        del max_regions
        raise ValueError("脏矩形超过画布容量")

    def style_type(self):
        """返回模拟样式类型。"""
        return self._style_type

    def style_name(self):
        """返回模拟自定义样式名。"""
        return "broken"

    def set_style(self, style_name):
        """记录回退目标样式。"""
        self.selected_style = style_name
        self._style_type = "builtin"
        return True

    def request_render(self, snapshot, force=False):
        """记录回退后重新提交的快照。"""
        self.rendered_snapshot = (snapshot, force)


class CustomStyleFallbackTest(unittest.TestCase):
    """覆盖自定义样式回退和内置样式异常透传。"""

    def _application(self, style_type):
        """构造不初始化硬件的最小应用实例。"""
        application = Application.__new__(Application)
        application._protocol = RecordingProtocol()
        application._renderer = FailingRenderer(style_type)
        application._failed_custom_style = None
        return application

    def test_custom_style_capacity_error_falls_back_to_default(self):
        """确认自定义样式异常后切换默认样式并打印两条诊断日志。"""
        application = self._application("custom")
        snapshot = {"cpu": {"percent": 50}}

        completed = application._update_renderer_with_fallback(snapshot)

        self.assertFalse(completed)
        self.assertEqual(application._failed_custom_style, "broken")
        self.assertEqual(application._renderer.selected_style, "default")
        self.assertEqual(application._renderer.rendered_snapshot, (snapshot, True))
        self.assertTrue(any("CUSTOM_STYLE:RENDER_FAILED:broken" in message
                            for message in application._protocol.messages))
        self.assertTrue(any("CONFIG:LCD_STYLE_FALLBACK:broken:default" in message
                            for message in application._protocol.messages))

    def test_builtin_style_capacity_error_is_not_suppressed(self):
        """确认内置样式容量错误继续交给顶层自动重启策略。"""
        application = self._application("builtin")

        with self.assertRaisesRegex(ValueError, "脏矩形超过画布容量"):
            application._update_renderer_with_fallback({})


if __name__ == "__main__":
    unittest.main()
