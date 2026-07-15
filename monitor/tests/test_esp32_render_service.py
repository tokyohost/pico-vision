"""验证 ESP32-S3 第二阶段渲染服务的线程边界和固定邮箱。"""

import _thread
import sys
import time
import unittest
from pathlib import Path


ESP32_ROOT = Path(__file__).resolve().parents[2] / "esp32-s3"
if str(ESP32_ROOT) not in sys.path:
    sys.path.insert(0, str(ESP32_ROOT))

_saved_config = sys.modules.pop("config", None)
try:
    from render_service import LatestFrameMailbox, RenderService  # noqa: E402
finally:
    sys.modules.pop("config", None)
    if _saved_config is not None:
        sys.modules["config"] = _saved_config
    try:
        sys.path.remove(str(ESP32_ROOT))
    except ValueError:
        pass


class FakeLcd:
    """记录由渲染所有者线程执行的 LCD 状态修改。"""

    def __init__(self):
        """初始化背光、旋转角度和调用线程记录。"""
        self._brightness = 100
        self._rotation = 0
        self.control_threads = []

    def set_backlight_brightness(self, brightness):
        """保存背光亮度和当前执行线程。"""
        brightness = int(brightness)
        changed = brightness != self._brightness
        self._brightness = brightness
        self.control_threads.append(_thread.get_ident())
        return changed

    def backlight_brightness(self):
        """返回当前模拟背光亮度。"""
        return self._brightness

    def rotation(self):
        """返回当前模拟屏幕旋转角度。"""
        return self._rotation


class FakeRenderer:
    """模拟可分两次完成一帧的 DashboardRenderer。"""

    instances = []

    def __init__(self, lcd, style_name="boot"):
        """保存 LCD、初始样式和创建线程。"""
        self.lcd = lcd
        self._style_name = style_name
        self._pending_steps = 0
        self._snapshot = None
        self._force = False
        self._creation_thread = _thread.get_ident()
        self._last_control_thread = None
        self.__class__.instances.append(self)

    def request_render(self, snapshot, force=False):
        """保存渲染快照并模拟两个区域等待刷新。"""
        self._snapshot = snapshot
        self._force = force
        self._pending_steps = 2

    def update_pending(self, max_regions=8, time_budget_us=None):
        """每次调用推进一个模拟区域并返回是否完成。"""
        del max_regions, time_budget_us
        if self._pending_steps <= 0:
            return False
        self._pending_steps -= 1
        return self._pending_steps == 0

    def is_rendering(self):
        """返回是否仍有模拟区域需要刷新。"""
        return self._pending_steps > 0

    def preload_style(self, style_name):
        """记录预加载样式命令的执行线程。"""
        del style_name
        self._last_control_thread = _thread.get_ident()
        return True

    def set_style(self, style_name):
        """记录样式切换及其执行线程。"""
        changed = style_name != self._style_name
        self._style_name = style_name
        self._last_control_thread = _thread.get_ident()
        if changed:
            self._pending_steps = 0
        return changed

    def set_rotation(self, rotation):
        """记录屏幕旋转及其执行线程。"""
        changed = int(rotation) != self.lcd._rotation
        self.lcd._rotation = int(rotation)
        self._last_control_thread = _thread.get_ident()
        return changed

    def abort_render(self, release_snapshot=False):
        """清除模拟待渲染区域并可释放快照。"""
        self._pending_steps = 0
        if release_snapshot:
            self._snapshot = None

    def capture_screen(self, chunk_writer, rows_per_chunk=8):
        """输出一块模拟截图并返回元数据。"""
        del rows_per_chunk
        chunk_writer(0, 0, 1, b"\x00\x00")
        return {"width": 1, "height": 1, "chunks": 1}

    def record_gc_us(self, elapsed_us):
        """保存模拟安全垃圾回收耗时。"""
        self._gc_us = int(elapsed_us)

    def style_name(self):
        """返回当前模拟样式名称。"""
        return self._style_name

    def style_type(self):
        """返回模拟内置样式类型。"""
        return "builtin"

    def canvas_backend(self):
        """返回模拟 Canvas 后端名称。"""
        return "fake"

    def last_render_ms(self):
        """返回固定模拟整帧耗时。"""
        return 4

    def last_profile(self):
        """返回固定模拟性能概要。"""
        return 100, 200, 2

    def last_detailed_profile(self):
        """返回固定模拟详细性能数据。"""
        return {
            "view_us": 10,
            "canvas_us": 100,
            "buffer_us": 20,
            "lcd_us": 200,
            "gc_us": getattr(self, "_gc_us", 0),
            "schedule_us": 30,
            "slowest_region_us": 180,
            "region_count": 2,
        }


class FailingThreadModule:
    """模拟无法创建工作线程但仍能提供锁的固件环境。"""

    @staticmethod
    def allocate_lock():
        """返回 CPython 原生锁供同步回退前初始化邮箱。"""
        return _thread.allocate_lock()

    @staticmethod
    def stack_size(size):
        """接受线程栈配置但不改变测试进程状态。"""
        del size

    @staticmethod
    def start_new_thread(function, arguments):
        """模拟底层因内存不足拒绝创建渲染线程。"""
        del function, arguments
        raise OSError("no thread memory")


class Esp32RenderServiceTest(unittest.TestCase):
    """覆盖双槽覆盖、线程所有权和同步回退行为。"""

    def setUp(self):
        """清空每个测试前的模拟渲染器实例记录。"""
        FakeRenderer.instances = []

    @staticmethod
    def _wait_completion(service, timeout_seconds=1):
        """在测试超时前轮询一次渲染完成通知。"""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if service.update_pending():
                return True
            time.sleep(0.001)
        return False

    def test_mailbox_keeps_latest_deep_copied_frame(self):
        """确认双槽邮箱覆盖旧帧且不共享主线程可变列表。"""
        mailbox = LatestFrameMailbox(_thread)
        first = {"history": [1, 2]}
        mailbox.publish(first, frame_version=1)
        first["history"].append(3)
        first_slot, first_frame = mailbox.take_latest()
        _first_sequence, first_payload = first_frame
        self.assertEqual(first_payload[0]["history"], (1, 2))
        mailbox.release(first_slot)

        mailbox.publish({"value": 1}, frame_version=1)
        mailbox.publish({"value": 2}, frame_version=2)

        slot_index, frame = mailbox.take_latest()
        _sequence, payload = frame
        snapshot, force, version = payload

        self.assertEqual(snapshot, {"value": 2})
        self.assertFalse(force)
        self.assertEqual(version, 2)
        self.assertEqual(mailbox.dropped_count(), 1)
        mailbox.release(slot_index)
        self.assertFalse(mailbox.has_pending())

    def test_block_mailbox_waits_until_pending_slot_is_consumed(self):
        """确认 block 策略不会覆盖待处理帧，并在槽释放后继续发布。"""
        mailbox = LatestFrameMailbox(_thread, policy="block")
        mailbox.publish({"value": 1}, frame_version=1)
        published = []

        def publish_second():
            """在辅助线程发布第二帧，用于验证阻塞解除时机。"""
            published.append(
                mailbox.publish({"value": 2}, frame_version=2)
            )

        _thread.start_new_thread(publish_second, ())
        time.sleep(0.02)
        self.assertEqual(published, [])
        first_slot, _first_frame = mailbox.take_latest()
        mailbox.release(first_slot)
        deadline = time.monotonic() + 1
        while not published and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertEqual(published, [2])
        self.assertEqual(mailbox.dropped_count(), 0)

    def test_thread_service_owns_renderer_and_lcd_controls(self):
        """确认渲染器创建、样式控制和背光控制均在工作线程执行。"""
        main_thread = _thread.get_ident()
        lcd = FakeLcd()
        service = RenderService(
            lcd,
            FakeRenderer,
            thread_enabled=True,
            thread_module=_thread,
        )
        try:
            self.assertTrue(service.start())
            renderer = FakeRenderer.instances[-1]
            self.assertNotEqual(renderer._creation_thread, main_thread)

            source = {"history": [10, 20]}
            service.request_render(source, frame_version=7)
            source["history"].append(30)
            self.assertFalse(service.set_style("boot"))
            self.assertTrue(self._wait_completion(service))
            self.assertEqual(renderer._snapshot["history"], (10, 20))
            self.assertEqual(service.last_completed_version(), 7)

            self.assertTrue(service.set_style("disk"))
            self.assertNotEqual(renderer._last_control_thread, main_thread)
            self.assertTrue(service.set_backlight_brightness(80))
            self.assertNotEqual(lcd.control_threads[-1], main_thread)
        finally:
            self.assertTrue(service.stop())

    def test_synchronous_fallback_preserves_renderer_interface(self):
        """确认关闭线程时仍可通过同一服务接口同步完成渲染。"""
        main_thread = _thread.get_ident()
        service = RenderService(
            FakeLcd(),
            FakeRenderer,
            thread_enabled=False,
            thread_module=_thread,
        )

        self.assertFalse(service.start())
        renderer = FakeRenderer.instances[-1]
        self.assertEqual(renderer._creation_thread, main_thread)
        self.assertFalse(service.accepts_while_rendering())
        service.request_render({"value": 1}, frame_version=9)
        self.assertFalse(service.update_pending(max_regions=1))
        self.assertTrue(service.update_pending(max_regions=1))
        self.assertEqual(service.last_completed_version(), 9)

    def test_thread_creation_failure_uses_synchronous_fallback(self):
        """确认线程创建失败时自动在通信主线程建立同步渲染器。"""
        main_thread = _thread.get_ident()
        service = RenderService(
            FakeLcd(),
            FakeRenderer,
            thread_enabled=True,
            thread_module=FailingThreadModule,
        )

        self.assertFalse(service.start())
        self.assertFalse(service.threaded())
        self.assertEqual(
            FakeRenderer.instances[-1]._creation_thread,
            main_thread,
        )


if __name__ == "__main__":
    unittest.main()
