"""验证自定义样式画布容量异常的内置样式回退流程。"""

import sys
import types
import unittest
from unittest import mock
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

    def set_command_services(self, services):
        """保存命令服务表。"""
        self.services = services


class FakeDashboardRenderer:
    """记录应用初始化时请求加载的首屏样式。"""

    created_styles = []

    def __init__(self, lcd, style_name):
        """记录 LCD 与首屏样式名称。"""
        del lcd
        self.created_styles.append(style_name)

    def request_render(self, snapshot, force=False):
        """忽略启动页渲染请求。"""
        del snapshot, force

    def is_rendering(self):
        """假定启动页已经刷新完成。"""
        return False


class FakeSnapshotCache:
    """提供启动阶段需要的数据缓存接口。"""

    def clear(self):
        """清空缓存占位。"""


class FakeDataReceiver:
    """提供启动阶段需要的数据接收器接口。"""

    def __init__(self, protocol, cache, led):
        """接收依赖但不执行硬件操作。"""
        del protocol, cache, led


class FakeLcdDevice:
    """提供启动阶段需要的 LCD 接口。"""

    def initialize(self):
        """模拟 LCD 初始化完成。"""

    def color_profile_name(self):
        """返回模拟屏幕色彩方案。"""
        return "fake"


class FakeLedController:
    """提供启动阶段需要的状态灯接口。"""

    def start(self):
        """模拟状态灯启动。"""


class FakeClock:
    """提供 MicroPython 时间函数的 CPython 替身。"""

    @staticmethod
    def ticks_ms():
        """返回固定毫秒时间。"""
        return 0

    @staticmethod
    def ticks_add(value, delta):
        """返回相加后的毫秒时间。"""
        return value + delta

    @staticmethod
    def sleep_ms(value):
        """忽略毫秒睡眠。"""
        del value


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


class BootSwitchRenderer:
    """模拟样式切换时可完成启动页刷新的渲染器。"""

    def __init__(self):
        """初始化当前样式、操作记录和刷新状态。"""
        self._style_name = "old"
        self.actions = []
        self._rendering = False

    def style_name(self):
        """返回当前模拟样式名。"""
        return self._style_name

    def set_style(self, style_name):
        """记录样式切换并更新当前样式名。"""
        self.actions.append(("set_style", style_name))
        if style_name == self._style_name:
            return False
        self._style_name = style_name
        return True

    def request_render(self, snapshot, force=False):
        """记录启动页渲染请求。"""
        self.actions.append(("request_render", snapshot, force))
        self._rendering = True

    def is_rendering(self):
        """返回是否仍有启动页区域待刷新。"""
        return self._rendering

    def update_pending(self, max_regions=8):
        """模拟刷新完成一个启动页区域。"""
        del max_regions
        self.actions.append(("update_pending", self._style_name))
        self._rendering = False
        return True


class CustomStyleFallbackTest(unittest.TestCase):
    """覆盖自定义样式回退和内置样式异常透传。"""

    def test_application_startup_always_uses_system_boot_style(self):
        """确认上电初始化固定加载系统启动页，不被自定义样式替换。"""
        dashboard_module = types.SimpleNamespace(
            DashboardRenderer=FakeDashboardRenderer,
        )
        data_receiver_module = types.SimpleNamespace(
            DataReceiver=FakeDataReceiver,
            SnapshotCache=FakeSnapshotCache,
        )
        lcd_module = types.SimpleNamespace(LcdDevice=FakeLcdDevice)
        board_manager_module = types.SimpleNamespace(
            get_board_profile=lambda name: types.SimpleNamespace(name=name),
        )
        led_module = types.SimpleNamespace(
            create_led_controller=lambda profile: FakeLedController(),
        )
        modules = {
            "dashboard": dashboard_module,
            "data_receiver": data_receiver_module,
            "lcd": lcd_module,
            "board_manager": board_manager_module,
            "led": led_module,
        }
        FakeDashboardRenderer.created_styles = []
        protocol = RecordingProtocol()

        with mock.patch.dict(sys.modules, modules), mock.patch("main.time", FakeClock):
            Application(protocol)

        self.assertEqual(FakeDashboardRenderer.created_styles, ["boot"])

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

    def test_style_switch_renders_system_boot_before_target_style(self):
        """确认切换指定样式前先进入系统启动页并完成刷新。"""
        application = Application.__new__(Application)
        application._protocol = RecordingProtocol()
        application._renderer = BootSwitchRenderer()
        application._boot_logs = []

        changed = application._set_style_after_system_boot("disk")

        self.assertTrue(changed)
        self.assertEqual(application._renderer.style_name(), "disk")
        self.assertEqual(application._renderer.actions[0], ("set_style", "boot"))
        self.assertEqual(application._renderer.actions[-1], ("set_style", "disk"))
        self.assertTrue(any(
            action[0] == "request_render"
            and action[1]["boot"]["logs"][-1] == "STYLE:PREPARE:disk"
            and action[2] is True
            for action in application._renderer.actions
        ))
        self.assertTrue(any("CONFIG:LCD_STYLE_PREPARE:disk" in message
                            for message in application._protocol.messages))


if __name__ == "__main__":
    unittest.main()
