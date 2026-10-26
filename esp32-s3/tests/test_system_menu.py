"""验证系统菜单按键隔离、设置确认、绘制和通信恢复。"""

import unittest
from unittest import mock

from buttonCommand import ButtonCommandDispatcher
from menu import SystemMenu
from menu.view import draw_menu
from main import Application
from dashboard import DashboardRenderer
from render_service import RenderService, RenderControlRequest
from tests.test_button_commands import FakeCommandHost
from tests import test_monitor_waiting_page as waiting_tests


class MenuInteractionTest(unittest.TestCase):
    """验证短按与长按互斥，以及菜单层级选择。"""

    def test_long_press_never_triggers_shortcut_or_confirmation(self):
        """进入菜单的整次长按只能打开菜单一次。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        dispatcher.dispatch([("function", event) for event in
                             ("press", "long_press", "repeat", "release")], host, {})
        self.assertEqual([("menu_open",)], host.calls)
        self.assertEqual("style", dispatcher.current().name)
        dispatcher.dispatch([("function", event) for event in
                             ("press", "long_press", "repeat", "release")], host, {})
        self.assertEqual([("menu_open",)], host.calls)

    def test_short_press_waits_for_release_and_respects_listener(self):
        """短按松手才交给样式，已消费的短按不轮换模式。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        dispatcher.dispatch([("function", "press")], host, {})
        self.assertEqual([], host.calls)
        host.handled_events.add(("function", "press"))
        dispatcher.dispatch([("function", "release")], host, {})
        self.assertEqual("style", dispatcher.current().name)
        self.assertEqual(["press", "release"], [call[2] for call in host.calls])

    def test_menu_consumes_direction_and_short_confirmation(self):
        """菜单期间不调用样式监听或旧快捷命令。"""
        dispatcher = ButtonCommandDispatcher()
        host = FakeCommandHost()
        host.menu_active = True
        dispatcher.dispatch([("style_next", "repeat"), ("function", "press"),
                             ("function", "release")], host, {})
        self.assertEqual([("menu", "style_next", "repeat"),
                          ("menu", "function", "press")], host.calls)

    def test_navigation_confirmation_and_back_stack(self):
        """首尾循环且每页末尾返回，子页返回保留父页位置。"""
        menu = SystemMenu()
        host = mock.Mock()
        host.system_menu_options.return_value = ([(10, "10%"), (55, "55%")], 55)
        host.apply_system_menu_setting.return_value = None
        menu.open()
        menu.move(-1)
        self.assertEqual("返回", menu.view()["items"][menu.view()["selected"]][1])
        menu.move(1)
        menu.move(1)
        menu.confirm(host, {})
        self.assertEqual(1, menu.view()["selected"])
        menu.move(-1)
        host.apply_system_menu_setting.assert_not_called()
        menu.confirm(host, {})
        self.assertEqual(10, menu.view()["current"])
        menu.move(-1)
        menu.confirm(host, {})
        self.assertEqual(1, menu.view()["selected"])
        menu.move(len(menu.view()["items"]) - 2)
        menu.confirm(host, {})
        self.assertFalse(menu.active)

    def test_setting_error_keeps_current_value_and_back_available(self):
        """设置失败时保留原值，仍能返回父页。"""
        menu = SystemMenu()
        host = mock.Mock()
        host.system_menu_options.return_value = ([(0, "0°"), (180, "180°")], 0)
        host.apply_system_menu_setting.return_value = "设置失败，请重试或返回"
        menu.open()
        menu.move(2)
        menu.confirm(host, {})
        menu.move(1)
        menu.confirm(host, {})
        self.assertEqual(0, menu.view()["current"])
        self.assertIn("失败", menu.view()["message"])
        menu.move(1)
        menu.confirm(host, {})
        self.assertEqual("root", menu.view()["key"])


class MenuSettingsTest(unittest.TestCase):
    """验证设备设置复用和仅确认后通知。"""

    def setUp(self):
        """创建不需要硬件的应用设置宿主。"""
        self.app = Application.__new__(Application)
        self.app._renderer = mock.Mock()
        self.app._protocol = mock.Mock()
        self.app._button_brightness_dirty = False
        self.app._button_network_unit_override = None
        self.app._last_display_network_unit = "MB"
        self.app._renderer.backlight_brightness.return_value = 55

    def test_brightness_includes_current_and_commits_once(self):
        """补入非整十亮度，确认一次只同步一次。"""
        items, current = self.app.system_menu_options("brightness")
        self.assertEqual(55, current)
        self.assertEqual([10, 20, 30, 40, 50, 55, 60, 70, 80, 90, 100],
                         [value for value, _ in items])
        self.app._renderer.backlight_brightness.return_value = 60
        self.app.apply_system_menu_setting("brightness", 60, None)
        self.app.commit_brightness_command()
        self.app._protocol.write.assert_called_once()
        self.assertIn(b'"lcd_brightness"', self.app._protocol.write.call_args.args[0])

    def test_rotation_unit_and_offline_style(self):
        """离线可调整旋转及单位，样式则提示先连接。"""
        self.assertIsNone(self.app.apply_system_menu_setting("rotation", 180, None))
        self.app._renderer.set_rotation.assert_called_with(180)
        self.app.apply_system_menu_setting("network_unit", "Mbps", None)
        self.app.apply_system_menu_setting("network_unit", "Mbps", None)
        self.assertEqual(2, self.app._protocol.write.call_count)
        self.assertEqual("请先连接监控端", self.app.apply_system_menu_setting("style", "default", None))

    def test_style_loading_failure_stays_recoverable(self):
        """样式异常转换为中文提示，不中断菜单。"""
        self.app._apply_button_style = mock.Mock(return_value=False)
        self.assertIn("失败", self.app.apply_system_menu_setting("style", "missing", {}))


class MenuRenderingTest(unittest.TestCase):
    """验证绘制边界和渲染控制线程的数据隔离。"""

    def test_worker_renders_menu_without_monitor_frames(self):
        """工作线程无数据帧时也执行菜单控制命令产生的绘制任务。"""
        service = RenderService.__new__(RenderService)
        renderer = mock.Mock()
        service._renderer_factory = mock.Mock(return_value=renderer)
        service._lcd = mock.Mock()
        service._initial_style = "boot"
        service._refresh_metadata = mock.Mock()
        service._set_worker_rendering = mock.Mock()
        service._record_completion = mock.Mock()
        service._running = True
        service._mailbox = mock.Mock()
        service._mailbox.take_latest.return_value = None
        service._control_queue = mock.Mock()
        request = RenderControlRequest("set_system_menu", ({"title": "系统菜单"},))
        service._control_queue.get.side_effect = [request, None]

        def complete_frame(**kwargs):
            """完成唯一菜单帧并停止测试工作循环。"""
            service._running = False
            return True

        renderer.update_pending.side_effect = complete_frame
        renderer.is_rendering.return_value = True
        service._worker_entry()
        renderer.update_pending.assert_called_once()
        service._record_completion.assert_called_once_with(renderer, None)

    def test_overlay_bypasses_style_and_restores_sync(self):
        """菜单绘制不执行主题钩子，并临时关闭整秒同步。"""
        renderer = DashboardRenderer.__new__(DashboardRenderer)
        renderer._style = mock.Mock()
        renderer._style.sync_visible_frame_to_second = True
        renderer.lcd = mock.Mock()
        renderer.canvas = mock.Mock()
        renderer._width, renderer._height = 240, 320
        renderer._snapshot = {"latest": True}
        renderer._force_frame = False
        view = {"title": "系统菜单"}
        with mock.patch("dashboard.time.ticks_ms", return_value=100, create=True), \
                mock.patch("dashboard.time.ticks_us", return_value=100, create=True), \
                mock.patch("dashboard.time.ticks_diff", side_effect=lambda a, b: a - b, create=True), \
                mock.patch("menu.view.draw_menu") as draw:
            renderer.set_system_menu(view)
            renderer.update()
            draw.assert_called_once_with(renderer.canvas, view, 240, 320)
            renderer._style.draw_visible.assert_not_called()
            renderer._style.prepare_frame.assert_not_called()
            renderer.lcd.set_visible_frame_second_sync.assert_called_with(False)
            renderer.set_system_menu(None)
            renderer.lcd.set_visible_frame_second_sync.assert_called_with(True)
            renderer.update()
            renderer._style.draw_visible.assert_called_once()

    def test_long_lists_fit_portrait_and_landscape(self):
        """长列表末尾选中项在横竖屏均可见且文本不越界。"""
        for width, height in ((240, 320), (320, 240)):
            canvas = mock.Mock()
            canvas.text_width.side_effect = lambda text, **kwargs: len(text) * 16
            view = {"title": "系统菜单", "items": [(i, "很长的中文菜单名称" * 4) for i in range(30)] + [(None, "返回")],
                    "selected": 30, "current": 2, "message": ""}
            draw_menu(canvas, view, width, height)
            texts = [call.args for call in canvas.text.call_args_list]
            self.assertTrue(any("返回" in args[2] for args in texts))
            for x, y, text, _ in texts:
                self.assertLessEqual(x + len(text) * 16, width)
                self.assertLessEqual(y + 16, height)

    def test_control_copies_view_and_dispatches_to_renderer(self):
        """提交后修改主线程列表不会改变渲染线程页面。"""
        service = RenderService.__new__(RenderService)
        service._submit_control = mock.Mock()
        view = {"items": [(1, "测试")], "selected": 0}
        service.set_system_menu(view)
        view["items"].append((None, "返回"))
        copied = service._submit_control.call_args.args[1]
        self.assertEqual(1, len(copied["items"]))
        service._refresh_metadata = mock.Mock()
        renderer = mock.Mock()
        request = RenderControlRequest("set_system_menu", (copied,))
        service._execute_control(renderer, request)
        renderer.set_system_menu.assert_called_once_with(copied)
        self.assertTrue(request.completed)
        self.assertIsNone(request.error)


class MenuMainLoopTest(unittest.TestCase):
    """复用通信测试宿主覆盖菜单期间的真实主循环。"""

    def test_menu_survives_disconnect_idle_and_reconnect(self):
        """菜单期间持续轮询通信，不切换待机或清空最新快照。"""
        harness = waiting_tests.MonitorWaitingPageTest()
        for idle, reconnect in ((False, False), (True, False), (False, True)):
            app, state = harness.create_application(idle_enabled=idle, now_ms=40000,
                                                    reconnect=reconnect, receiver_busy=True)
            app._system_menu = SystemMenu()
            app._system_menu.open()
            harness.run_application(app, state)
            self.assertTrue(app.system_menu_active())
            self.assertEqual(0, app._cache.clears)
            self.assertEqual("default", state["style"])
            self.assertEqual(2, app._led.update.call_count)
            self.assertEqual(2, app._update_renderer_with_fallback.call_count)
            if reconnect:
                self.assertTrue(app._cache.snapshot["reconnected"])

    def test_exit_uses_latest_snapshot_or_waiting_page(self):
        """退出时采用最新快照，断线且禁止待机时清空旧数据。"""
        harness = waiting_tests.MonitorWaitingPageTest()
        for disconnected in (False, True):
            app, state = harness.create_application(idle_enabled=False)
            app._cache.snapshot = {"display": {"style": "default", "idle_enabled": False}, "latest": True}
            app._monitor_timed_out = mock.Mock(return_value=disconnected)
            with mock.patch("main.time.ticks_ms", return_value=6000, create=True), \
                    mock.patch("main.time.ticks_diff", side_effect=lambda a, b: a - b, create=True):
                app._close_system_menu()
            app._renderer.set_system_menu.assert_called_with(None)
            if disconnected:
                self.assertIsNone(app._cache.snapshot)
                self.assertEqual("boot", state["style"])
            else:
                self.assertTrue(app._renderer.request_render.call_args.args[0]["latest"])


if __name__ == "__main__":
    unittest.main()
