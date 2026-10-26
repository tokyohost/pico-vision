"""验证禁止待机时，通信超时返回等待页且新快照能够恢复监控。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


ESP32_S3_ROOT = Path(__file__).resolve().parents[1]
if str(ESP32_S3_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_S3_ROOT))

from main import Application  # noqa: E402


class RecordingCache:
    """记录主循环对过期快照的清理及重新连接后的快照替换。"""

    def __init__(self, snapshot):
        """保存一份已显示的监控快照和对应版本。"""
        self.snapshot = snapshot
        self.version = 7
        self.clears = 0

    def latest(self):
        """返回当前可渲染的快照和版本。"""
        return self.snapshot, self.version

    def last_update_ms(self):
        """将最后一次有效快照固定在测试时间零点。"""
        return 0 if self.snapshot is not None else None

    def next_refresh_ms(self, interval_ms, now_ms):
        """安排下一次时钟刷新，避免测试中的重复刷新影响断线判断。"""
        return now_ms + interval_ms

    def clear(self):
        """记录清理次数并使过期监控快照立即失效。"""
        self.clears += 1
        self.snapshot = None
        self.version += 1

    def receive(self, snapshot):
        """模拟协议接收到一份完整的新监控快照。"""
        self.snapshot = snapshot
        self.version += 1


class MonitorWaitingPageTest(unittest.TestCase):
    """直接运行应用主循环，覆盖断线、忙状态和重新连接的页面转换。"""

    def create_application(self, idle_enabled=False, receiver_busy=False,
                           renderer_busy=False, now_ms=6000,
                           reconnect=False, fresh_message=False, send_interval_ms=500):
        """创建已显示监控页的应用，以两轮主循环模拟超时及后续恢复。"""
        application = Application.__new__(Application)
        state = {"now": 0, "calls": 0, "style": "default", "rendering": False}
        display = {"style": "default", "idle_enabled": idle_enabled,
                   "collection_interval_ms": send_interval_ms}
        application._cache = RecordingCache({"display": display, "expired_cpu": 99})
        application._protocol = mock.Mock()
        application._protocol.last_message_ms.return_value = 0
        application._renderer = mock.Mock()
        application._renderer.is_rendering.side_effect = lambda: state["rendering"]
        application._renderer.style_name.side_effect = lambda: state["style"]
        application._renderer.accepts_while_rendering.return_value = False
        application._renderer.set_backlight_brightness.return_value = False
        application._renderer.set_rotation.return_value = False

        def set_style(style):
            """模拟切换样式时清除过期渲染任务。"""
            changed = state["style"] != style
            state["style"] = style
            state["rendering"] = False
            return changed

        def receive():
            """推进两轮通信时间，并在需要时提交重新连接的新快照。"""
            index = state["calls"]
            state["calls"] += 1
            if index >= 2:
                raise StopIteration("测试主循环已完成")
            state["now"] = now_ms + index * 250
            if index == 0:
                state["rendering"] = renderer_busy
                application._renderer.request_render.reset_mock()
            has_message = (index == 0 and fresh_message) or (index == 1 and reconnect)
            if has_message:
                application._protocol.last_message_ms.return_value = state["now"]
                application._cache.receive({"display": display, "reconnected": True})
            return has_message

        application._renderer.set_style.side_effect = set_style
        application._receiver = mock.Mock()
        application._receiver.update.side_effect = receive
        application._receiver.is_busy.return_value = receiver_busy
        application._sdk_bootloader = None
        application._led = mock.Mock()
        application._buttons = mock.Mock()
        application._buttons.update.return_value = ()
        application._handle_button_actions = mock.Mock()
        application._update_renderer_with_fallback = mock.Mock(return_value=False)
        application._write_render_profile_if_needed = mock.Mock()
        application._set_style_after_system_boot = mock.Mock(side_effect=set_style)
        application._monitor_connected = True
        application._monitor_interval_ms = send_interval_ms
        application._idle_enabled = idle_enabled
        application._idle_timeout_ms = 30000
        application._idle_style = "idle"
        application._idle_active = False
        application._idle_wait_started_ms = 0
        application._rendering_version = application._cache.version
        application._next_clock_render = 100000
        application._next_boot_animation = 0
        application._boot_frame = 0
        application._boot_logs = []
        application._transport = mock.Mock()
        application._transport.wifi_status.return_value = {
            "enabled": True, "available": True, "connected": True,
            "ssid": "测试网络", "ip": "192.168.1.10",
        }
        application._button_hint_until_ms = None
        application._button_hint_snapshot = None
        application._button_hint_label = None
        application._button_style_override = None
        application._button_brightness_override = None
        application._button_rotation_override = None
        application._button_network_unit_override = None
        application._last_display_style = "default"
        application._last_display_brightness = 100
        application._last_display_rotation = 0
        application._last_display_network_unit = "MB"
        return application, state

    def run_application(self, application, state):
        """使用确定的毫秒时钟执行真实主循环，并在两轮后退出测试。"""
        with mock.patch("main.memory_usage", return_value=(1, 2)), \
                mock.patch("main.time.ticks_ms", side_effect=lambda: state["now"], create=True), \
                mock.patch("main.time.ticks_diff", side_effect=lambda end, start: end - start, create=True), \
                mock.patch("main.time.ticks_add", side_effect=lambda start, delta: start + delta, create=True), \
                mock.patch("main.time.sleep_ms", create=True):
            with self.assertRaises(StopIteration):
                application.run()

    def test_disabled_idle_timeout_returns_to_waiting_with_live_wifi(self):
        """禁止待机时清理旧数据，展示带实时 Wi-Fi、日志和进度的等待页。"""
        application, state = self.create_application()
        self.run_application(application, state)
        self.assertEqual("boot", state["style"])
        self.assertFalse(application._monitor_connected)
        self.assertFalse(application._idle_active)
        self.assertIsNone(application._cache.snapshot)
        self.assertEqual(1, application._cache.clears)
        application._renderer.set_style.assert_called_once_with("boot")
        boot = application._renderer.request_render.call_args.args[0]["boot"]
        self.assertEqual(100, boot["progress"])
        self.assertIn("MONITOR:TIMEOUT", boot["logs"])
        from i18n import t

        self.assertTrue(boot["status"].startswith(t("boot.waiting")))
        self.assertEqual("测试网络", boot["wifi"]["ssid"])
        self.assertTrue(boot["wifi"]["connected"])

    def test_timeout_is_not_blocked_by_partial_receive_or_active_render(self):
        """接收残留半帧或正在渲染旧数据时，也应及时回到等待连接页。"""
        for rendering in (False, True):
            with self.subTest(rendering=rendering):
                application, state = self.create_application(
                    receiver_busy=True, renderer_busy=rendering,
                )
                self.run_application(application, state)
                self.assertEqual("boot", state["style"])
                self.assertIsNone(application._cache.snapshot)

    def test_before_deadline_keeps_monitoring_page(self):
        """尚未达到通信超时阈值时保留当前监控页面与数据。"""
        application, state = self.create_application(now_ms=4500)
        self.run_application(application, state)
        self.assertEqual("default", state["style"])
        self.assertTrue(application._monitor_connected)
        self.assertEqual(0, application._cache.clears)

    def test_timeout_follows_adaptive_json_send_interval(self):
        """发送间隔自适应增至一点五秒时，应等待十五秒，不能仍按五秒超时。"""
        for now_ms, expected_style in ((6000, "default"), (15000, "boot")):
            with self.subTest(now_ms=now_ms):
                application, state = self.create_application(now_ms=now_ms, send_interval_ms=1500)
                self.run_application(application, state)
                self.assertEqual(expected_style, state["style"])

    def test_enabled_idle_keeps_configured_standby_policy(self):
        """允许待机时继续保留最后数据，达到待机阈值后进入待机样式。"""
        for now_ms, expected_style in ((6000, "default"), (31000, "idle")):
            with self.subTest(now_ms=now_ms):
                application, state = self.create_application(idle_enabled=True, now_ms=now_ms)
                self.run_application(application, state)
                self.assertEqual(expected_style, state["style"])
                self.assertEqual(0, application._cache.clears)

    def test_new_snapshot_restores_monitoring_after_waiting(self):
        """重新接收完整快照后恢复监控样式，旧数据不应带入新快照。"""
        application, state = self.create_application(reconnect=True)
        self.run_application(application, state)
        self.assertEqual("default", state["style"])
        self.assertTrue(application._monitor_connected)
        self.assertEqual(1, application._cache.clears)
        self.assertTrue(application._cache.snapshot["reconnected"])
        self.assertNotIn("expired_cpu", application._cache.snapshot)
        rendered = application._renderer.request_render.call_args.args[0]
        self.assertTrue(rendered["reconnected"])

    def test_fresh_message_prevents_false_timeout(self):
        """本轮收到有效消息时应以新接收时间为准，避免错误清理新快照。"""
        application, state = self.create_application(fresh_message=True)
        self.run_application(application, state)
        self.assertEqual("default", state["style"])
        self.assertEqual(0, application._cache.clears)

    def test_waiting_page_discards_pending_button_hint(self):
        """回到等待页时取消旧按键提示，防止提示到期后重绘已失效监控数据。"""
        application, state = self.create_application()
        application._button_hint_until_ms = 6200
        application._button_hint_snapshot = application._cache.snapshot
        application._button_hint_label = "旧按键提示"
        self.run_application(application, state)
        self.assertEqual("boot", state["style"])
        self.assertIsNone(application._button_hint_until_ms)
        self.assertIsNone(application._button_hint_snapshot)
        self.assertIsNone(application._button_hint_label)
        self.assertTrue(all("boot" in call.args[0]
                            for call in application._renderer.request_render.call_args_list))


if __name__ == "__main__":
    unittest.main()
