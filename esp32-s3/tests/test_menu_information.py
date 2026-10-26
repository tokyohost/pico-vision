"""验证只读信息采集、详情全文展示及运行状态定时刷新。"""

import unittest
from types import SimpleNamespace
from unittest import mock

import i18n
from menu import SystemMenu
from menu import information
from menu.view import wrap_text, draw_menu
from main import Application
from dashboard import DashboardRenderer
from render_service import RenderService, RenderControlRequest
from tests import test_monitor_waiting_page as waiting_tests


class InformationProviderTest(unittest.TestCase):
    """覆盖真实数据来源、字段故障隔离和运行状态变化。"""

    def setUp(self):
        """固定中文文案，测试结束后恢复原语言。"""
        patcher = mock.patch.object(i18n, "_locale", "zh-CN")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_static_values_reuse_sdk_and_identity_and_survive_missing_lcd(self):
        """版本和 ID 使用既有接口，面板失败不影响其他字段。"""
        with mock.patch.object(information, "runtime_sdk_version", return_value="v1.2.3-custom") as sdk, \
                mock.patch.object(information, "device_uuid", return_value="12345678-1234-8123-8123-123456789abc") as uuid:
            fields = {key: value for key, _, value in information.static_information(None)}
        self.assertEqual("v1.2.3-custom", fields["sdk"])
        self.assertEqual("12345678-1234-8123-8123-123456789abc", fields["device_id"])
        self.assertEqual(information.config.FIRMWARE_VERSION, fields["firmware"])
        self.assertEqual("不可用", fields["resolution"])
        sdk.assert_called_once()
        uuid.assert_called_once()

    def test_runtime_values_and_fault_isolation(self):
        """内存失败时仍展示传输和无线状态，且不主动触发回收。"""
        transport = mock.Mock()
        transport.status.return_value = {"mode": "usb", "connected": True}
        transport.wifi_status.return_value = {"enabled": True, "available": True,
                                             "connected": True, "ssid": "办公室网络", "ip": "192.168.1.2"}
        with mock.patch.object(information.gc, "mem_alloc", return_value=25, create=True), \
                mock.patch.object(information.gc, "mem_free", return_value=75, create=True), \
                mock.patch.object(information.gc, "collect") as collect:
            fields = {key: value for key, _, value in information.dynamic_information(transport)}
            self.assertIn("25.0%", fields["memory"])
            self.assertIn("100 B", fields["memory"])
            self.assertEqual("USB / 已连接", fields["connection"])
            self.assertEqual("办公室网络", fields["ssid"])
            collect.assert_not_called()
        with mock.patch.object(information.gc, "mem_alloc", side_effect=RuntimeError(), create=True):
            fields = {key: value for key, _, value in information.dynamic_information(transport)}
        self.assertEqual("不可用", fields["memory"])
        self.assertEqual("192.168.1.2", fields["ip"])
        transport.scan.assert_not_called()
        transport.connect.assert_not_called()

    def test_connection_changes_and_disabled_wifi(self):
        """区分 USB、无线、断线和禁用 Wi-Fi，断线不保留旧 IP。"""
        transport = mock.Mock()
        for mode, connected, expected in (("usb", True, "USB / 已连接"),
                                           ("websocket", True, "Wi-Fi / 已连接"),
                                           ("none", False, "未连接")):
            transport.status.return_value = {"mode": mode, "connected": connected}
            transport.wifi_status.return_value = {"enabled": False, "ip": "旧地址"}
            values = {key: value for key, _, value in information.dynamic_information(transport)}
            self.assertEqual(expected, values["connection"])
            self.assertEqual("已禁用", values["wifi"])
            self.assertEqual("未连接", values["ip"])
        transport.status.side_effect = OSError()
        transport.wifi_status.side_effect = RuntimeError()
        values = {key: value for key, _, value in information.dynamic_information(transport)}
        self.assertEqual("不可用", values["connection"])
        self.assertEqual("不可用", values["wifi"])

    def test_application_samples_static_only_on_entry(self):
        """定时采样只读动态字段，关于页不读取设备状态。"""
        app = Application.__new__(Application)
        app._lcd = SimpleNamespace(panel_profile=SimpleNamespace(width=240, height=320))
        app._transport = None
        with mock.patch.object(information, "static_information", return_value=[]) as static, \
                mock.patch.object(information, "dynamic_information", return_value=[]) as dynamic:
            app.system_menu_information("system_info")
            app.system_menu_information("system_info", dynamic=True)
            about = app.system_menu_information("about")
        static.assert_called_once_with(app._lcd)
        self.assertEqual(2, dynamic.call_count)
        self.assertIn(("author", "作者", "tokyohost"), about)
        self.assertEqual("https://github.com/tokyohost/omniwatch-doc", about[-1][2])

    def test_main_loop_only_submits_changed_information(self):
        """主循环采样变化后提交一帧，同时继续推进通信和 LED。"""
        harness = waiting_tests.MonitorWaitingPageTest()
        app, state = harness.create_application(now_ms=40000, reconnect=True)
        app._system_menu = SystemMenu()
        app._system_menu.open()
        app._system_menu.move(4)
        app.system_menu_information = mock.Mock(return_value=[("memory", "内存使用", "旧值")])
        app._system_menu.confirm(app, {})
        app._system_menu._next_refresh = 40000
        app.system_menu_information.return_value = [("memory", "内存使用", "新值")]
        app.system_menu_information.reset_mock()
        harness.run_application(app, state)
        app.system_menu_information.assert_called_once_with("system_info", dynamic=True)
        app._renderer.set_system_menu.assert_called_once()
        self.assertEqual(2, app._led.update.call_count)
        self.assertTrue(app._cache.snapshot["reconnected"])


class InformationNavigationTest(unittest.TestCase):
    """覆盖信息页、详情页和设置页之间的操作隔离。"""

    def setUp(self):
        """建立带实际换行函数的模拟信息宿主。"""
        self.menu = SystemMenu()
        self.host = mock.Mock()
        self.host.system_menu_information.return_value = [("sdk", "SDK 版本", "v1"),
                                                          ("memory", "内存使用", "内存初值")]
        self.canvas = mock.Mock()
        self.canvas.text_width.side_effect = lambda text, **kwargs: sum(8 if ord(c) < 128 else 16 for c in text)
        self.host.system_menu_detail_lines.side_effect = lambda text: wrap_text(self.canvas, text, 224)
        self.menu.open()

    def enter_info(self):
        """从根页进入系统信息。"""
        self.menu.move(4)
        self.menu.confirm(self.host, {})

    def test_order_details_return_and_no_setting_actions(self):
        """信息入口顺序固定，正文确认无副作用且逐级返回保留位置。"""
        self.assertEqual(["style", "brightness", "rotation", "network_unit", "system_info", "about", None],
                         [item[0] for item in self.menu.view()["items"]])
        self.enter_info()
        self.menu.move(1)
        self.menu.confirm(self.host, {})
        self.assertEqual("detail", self.menu.view()["type"])
        before = self.menu.view()
        self.menu.confirm(self.host, {})
        self.assertEqual(before, self.menu.view())
        self.menu.move(-1)
        self.assertIsNone(self.menu.view()["items"][self.menu.view()["selected"]][0])
        self.menu.confirm(self.host, {})
        self.assertEqual(1, self.menu.view()["selected"])
        self.menu.move(1)
        self.menu.confirm(self.host, {})
        self.assertEqual(4, self.menu.view()["selected"])
        self.host.apply_system_menu_setting.assert_not_called()

    def test_refresh_cadence_preserves_selection_and_stops_on_exit(self):
        """每秒只采样一次，值不变不提交画面，离开后不再采样。"""
        self.enter_info()
        self.menu.move(1)
        self.assertFalse(self.menu.refresh(self.host, 0))
        self.assertFalse(self.menu.refresh(self.host, 999))
        self.host.system_menu_information.return_value = [("memory", "内存使用", "更新值")]
        self.assertTrue(self.menu.refresh(self.host, 1000))
        self.assertEqual(1, self.menu.view()["selected"])
        self.assertEqual(("sdk", "SDK 版本", "v1"), self.menu.view()["fields"][0])
        self.assertFalse(self.menu.refresh(self.host, 2000))
        self.menu.move(1)
        self.menu.confirm(self.host, {})
        self.host.system_menu_information.reset_mock()
        self.assertFalse(self.menu.refresh(self.host, 3000))
        self.host.system_menu_information.assert_not_called()

    def test_detail_refresh_keeps_scroll_and_back_selection(self):
        """动态正文改变后保留行位置，已选择返回时继续选择返回。"""
        self.enter_info()
        self.menu.move(1)
        self.menu.confirm(self.host, {})
        self.menu.refresh(self.host, 0)
        self.host.system_menu_information.return_value = [("memory", "内存使用", "x" * 160)]
        self.assertTrue(self.menu.refresh(self.host, 1000))
        self.menu.move(2)
        self.host.system_menu_information.return_value = [("memory", "内存使用", "y" * 170)]
        self.assertTrue(self.menu.refresh(self.host, 2000))
        self.assertEqual(2, self.menu.view()["selected"])
        self.menu.move(len(self.menu.view()["items"]) - 3)
        self.host.system_menu_information.return_value = [("memory", "内存使用", "z")]
        self.assertTrue(self.menu.refresh(self.host, 3000))
        self.assertIsNone(self.menu.view()["items"][self.menu.view()["selected"]][0])

    def test_about_never_samples_dynamic_information(self):
        """关于页面及其详情不触发一秒采样。"""
        self.menu.move(5)
        self.menu.confirm(self.host, {})
        self.menu.confirm(self.host, {})
        self.host.system_menu_information.reset_mock()
        self.menu.refresh(self.host, 0)
        self.menu.refresh(self.host, 5000)
        self.host.system_menu_information.assert_not_called()

    def test_full_text_visible_across_all_detail_pages(self):
        """横竖屏浏览可还原完整 UUID、长版本号、中文 SSID 和网址。"""
        texts = ["12345678-1234-8123-8123-123456789abc", "v1.0-" + "build" * 45,
                 "办公室无线网络" * 15, "https://github.com/tokyohost/omniwatch-doc"]
        for width, height in ((240, 320), (320, 240)):
            for text in texts:
                lines = wrap_text(self.canvas, text, width - 16)
                self.assertEqual(text, "".join(lines))
                self.assertTrue(all(self.canvas.text_width(line) <= width - 16 for line in lines))
                for index, line in enumerate(lines):
                    self.canvas.text.reset_mock()
                    view = {"type": "detail", "title": "详情", "items": list(enumerate(lines)) + [(None, "返回")],
                            "selected": index, "current": None}
                    draw_menu(self.canvas, view, width, height)
                    self.assertIn(line, [call.args[2] for call in self.canvas.text.call_args_list])

    def test_layout_runs_through_render_control(self):
        """详情排版通过控制队列分派给画布所有者线程。"""
        service = RenderService.__new__(RenderService)
        service._submit_control = mock.Mock(return_value=["全文"])
        self.assertEqual(["全文"], service.wrap_system_menu_text("全文"))
        renderer = DashboardRenderer.__new__(DashboardRenderer)
        renderer.canvas = self.canvas
        renderer._width = 240
        request = RenderControlRequest("wrap_system_menu_text", ("完整设备 ID",))
        service._refresh_metadata = mock.Mock()
        service._execute_control(renderer, request)
        self.assertIsNone(request.error)
        self.assertEqual(["完整设备 ID"], request.result)


if __name__ == "__main__":
    unittest.main()
