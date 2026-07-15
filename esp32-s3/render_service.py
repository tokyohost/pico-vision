#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.


"""为 ESP32-S3 提供固定邮箱、控制队列和独占 LCD 的渲染服务。"""


import time

from config import (
    RENDER_CONTROL_QUEUE_CAPACITY,
    RENDER_CONTROL_TIMEOUT_MS,
    RENDER_FRAME_POLICY,
    RENDER_SERVICE_START_TIMEOUT_MS,
    RENDER_SERVICE_THREAD_ENABLED,
    RENDER_WORKER_MAX_REGIONS,
    RENDER_WORKER_STACK_SIZE,
)


FRAME_POLICY_LATEST = "latest"
FRAME_POLICY_BLOCK = "block"
FRAME_POLICIES = (FRAME_POLICY_LATEST, FRAME_POLICY_BLOCK)


def normalize_frame_policy(policy):
    """规范化新帧背压策略，并拒绝会造成不确定排队行为的配置。"""
    normalized = str(policy or FRAME_POLICY_LATEST).strip().lower()
    if normalized not in FRAME_POLICIES:
        raise ValueError("未知渲染帧策略：{}".format(policy))
    return normalized


def _ticks_ms():
    """返回兼容 MicroPython 与 CPython 的单调毫秒时间。"""
    provider = getattr(time, "ticks_ms", None)
    if callable(provider):
        return provider()
    return int(time.monotonic() * 1000)


def _ticks_add(value, delta):
    """按照当前运行时能力计算可回绕的毫秒时间。"""
    provider = getattr(time, "ticks_add", None)
    return provider(value, delta) if callable(provider) else value + delta


def _ticks_diff(current, started):
    """按照当前运行时能力计算可回绕的毫秒差值。"""
    provider = getattr(time, "ticks_diff", None)
    return provider(current, started) if callable(provider) else current - started


def _sleep_ms(delay_ms):
    """以毫秒为单位让出执行权并兼容 CPython 测试环境。"""
    provider = getattr(time, "sleep_ms", None)
    if callable(provider):
        provider(delay_ms)
    else:
        time.sleep(max(0, delay_ms) / 1000)


def _clone_render_value(value):
    """递归复制渲染数据，避免主线程和工作线程共享可变容器。"""
    if isinstance(value, dict):
        return {
            key: _clone_render_value(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return tuple(_clone_render_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_clone_render_value(item) for item in value)
    return value


class LatestFrameMailbox:
    """使用两个固定槽按 latest 或 block 策略发布渲染快照。"""

    def __init__(self, thread_module, policy=FRAME_POLICY_LATEST):
        """创建双槽邮箱、短时状态锁和指定的新帧背压策略。"""
        self._lock = thread_module.allocate_lock()
        self._policy = normalize_frame_policy(policy)
        self._slots = [None, None]
        self._ready_index = -1
        self._reading_index = -1
        self._next_index = 0
        self._sequence = 0
        self._dropped = 0

    def publish(self, snapshot, force=False, frame_version=None):
        """深拷贝并按覆盖或阻塞策略发布快照，返回内部递增序号。"""
        payload = (_clone_render_value(snapshot or {}), bool(force), frame_version)
        while True:
            self._lock.acquire()
            try:
                if self._policy == FRAME_POLICY_BLOCK and self._ready_index >= 0:
                    should_wait = True
                else:
                    should_wait = False
                    index = self._next_index
                    if index == self._reading_index:
                        index = 1 - index
                    if self._ready_index >= 0:
                        index = self._ready_index
                        self._dropped += 1
                    self._sequence += 1
                    self._slots[index] = (self._sequence, payload)
                    self._ready_index = index
                    self._next_index = 1 - index
                    return self._sequence
            finally:
                self._lock.release()
            if should_wait:
                _sleep_ms(1)

    def take_latest(self):
        """取得最新就绪帧及槽位编号，没有数据时返回空值。"""
        self._lock.acquire()
        try:
            if self._ready_index < 0:
                return None
            index = self._ready_index
            self._ready_index = -1
            self._reading_index = index
            return index, self._slots[index]
        finally:
            self._lock.release()

    def release(self, index):
        """释放工作线程已经登记到渲染器中的读取槽。"""
        self._lock.acquire()
        try:
            if self._reading_index == index:
                self._slots[index] = None
                self._reading_index = -1
        finally:
            self._lock.release()

    def discard_pending(self):
        """丢弃尚未消费的帧并保留正在读取的槽。"""
        self._lock.acquire()
        try:
            if self._ready_index >= 0:
                self._slots[self._ready_index] = None
                self._ready_index = -1
                self._dropped += 1
        finally:
            self._lock.release()

    def has_pending(self):
        """返回邮箱中是否存在尚未消费的最新帧。"""
        self._lock.acquire()
        try:
            return self._ready_index >= 0
        finally:
            self._lock.release()

    def dropped_count(self):
        """返回被更新快照覆盖或主动丢弃的累计帧数。"""
        self._lock.acquire()
        try:
            return self._dropped
        finally:
            self._lock.release()

    def policy(self):
        """返回邮箱当前使用的 latest 或 block 背压策略。"""
        return self._policy


class RenderControlRequest:
    """保存一条不可丢弃的同步渲染控制命令及执行结果。"""

    def __init__(self, action, arguments):
        """记录控制动作、参数和初始完成状态。"""
        self.action = action
        self.arguments = arguments
        self.result = None
        self.error = None
        self.completed = False


class FixedControlQueue:
    """使用固定数组保存样式、旋转和截图等同步控制命令。"""

    def __init__(self, thread_module, capacity):
        """按指定容量创建环形控制队列。"""
        self._lock = thread_module.allocate_lock()
        self._items = [None] * max(1, int(capacity))
        self._read_index = 0
        self._write_index = 0
        self._count = 0

    def put(self, request, timeout_ms):
        """在超时前把不可丢弃控制命令写入固定队列。"""
        deadline = _ticks_add(_ticks_ms(), max(1, int(timeout_ms)))
        while True:
            self._lock.acquire()
            try:
                if self._count < len(self._items):
                    self._items[self._write_index] = request
                    self._write_index = (self._write_index + 1) % len(self._items)
                    self._count += 1
                    return
            finally:
                self._lock.release()
            if _ticks_diff(_ticks_ms(), deadline) >= 0:
                raise RuntimeError("RENDER_CONTROL_QUEUE_TIMEOUT")
            _sleep_ms(1)

    def get(self):
        """取出最早的控制命令，没有命令时返回空值。"""
        self._lock.acquire()
        try:
            if self._count <= 0:
                return None
            request = self._items[self._read_index]
            self._items[self._read_index] = None
            self._read_index = (self._read_index + 1) % len(self._items)
            self._count -= 1
            return request
        finally:
            self._lock.release()


class RenderService:
    """隔离通信主线程与 DashboardRenderer，并统一提供同步回退接口。"""

    def __init__(
        self,
        lcd,
        renderer_factory,
        style_name="boot",
        thread_enabled=RENDER_SERVICE_THREAD_ENABLED,
        thread_module=None,
        frame_policy=RENDER_FRAME_POLICY,
    ):
        """保存渲染依赖，并准备线程模式或同步回退模式的公共状态。"""
        self._lcd = lcd
        self._renderer_factory = renderer_factory
        self._initial_style = style_name
        self._thread_enabled = bool(thread_enabled)
        self._thread_module = thread_module
        self._frame_policy = normalize_frame_policy(frame_policy)
        self._mailbox = None
        self._control_queue = None
        self._renderer = None
        self._threaded = False
        self._running = False
        self._ready = False
        self._stopped = False
        self._startup_error = None
        self._worker_error = None
        self._worker_rendering = False
        self._completed_count = 0
        self._reported_count = 0
        self._active_frame_version = None
        self._last_completed_version = None
        self._last_render_ms = 0
        self._last_profile = (0, 0, 0)
        self._last_detailed_profile = {
            "view_us": 0,
            "canvas_us": 0,
            "buffer_us": 0,
            "lcd_us": 0,
            "gc_us": 0,
            "schedule_us": 0,
            "slowest_region_us": 0,
            "region_count": 0,
        }
        self._style_name = style_name
        self._style_type = "builtin"
        self._canvas_backend = "python"
        self._backlight_brightness = lcd.backlight_brightness()
        self._rotation = lcd.rotation()

    def start(self):
        """启动渲染工作线程；线程不可用或初始化失败时回退同步模式。"""
        if self._renderer is not None or self._running:
            return self._threaded
        thread_module = self._thread_module
        if thread_module is None and self._thread_enabled:
            try:
                import _thread as thread_module
            except ImportError:
                thread_module = None
        if not self._thread_enabled or thread_module is None:
            self._start_synchronous()
            return False
        self._thread_module = thread_module
        self._mailbox = LatestFrameMailbox(thread_module, self._frame_policy)
        self._control_queue = FixedControlQueue(
            thread_module, RENDER_CONTROL_QUEUE_CAPACITY
        )
        self._running = True
        stack_size = getattr(thread_module, "stack_size", None)
        try:
            if callable(stack_size):
                stack_size(RENDER_WORKER_STACK_SIZE)
            thread_module.start_new_thread(self._worker_entry, ())
        except Exception:
            self._running = False
            self._start_synchronous()
            return False
        finally:
            if callable(stack_size):
                stack_size(0)
        deadline = _ticks_add(_ticks_ms(), RENDER_SERVICE_START_TIMEOUT_MS)
        while not self._ready:
            if _ticks_diff(_ticks_ms(), deadline) >= 0:
                self._running = False
                raise RuntimeError("RENDER_WORKER_START_TIMEOUT")
            _sleep_ms(1)
        if self._startup_error is not None:
            error = self._startup_error
            self._running = False
            self._start_synchronous()
            if self._renderer is None:
                raise error
            return False
        self._threaded = True
        return True

    def _start_synchronous(self):
        """在当前主线程创建渲染器并启用兼容同步服务。"""
        self._renderer = self._renderer_factory(
            self._lcd, style_name=self._initial_style
        )
        self._threaded = False
        self._ready = True
        self._running = False
        self._refresh_metadata(self._renderer)

    def _worker_entry(self):
        """在工作线程创建并持续推进唯一 DashboardRenderer 实例。"""
        try:
            renderer = self._renderer_factory(
                self._lcd, style_name=self._initial_style
            )
            self._renderer = renderer
            self._refresh_metadata(renderer)
        except Exception as error:
            self._startup_error = error
            self._ready = True
            self._stopped = True
            return
        self._ready = True
        active_frame = False
        active_version = None
        while self._running:
            control = self._control_queue.get()
            if control is not None:
                self._execute_control(renderer, control)
                style_interrupted = (
                    control.action == "set_style"
                    and (bool(control.result) or control.error is not None)
                )
                if control.action == "abort_render" or style_interrupted:
                    active_frame = False
                    active_version = None
                    self._set_worker_rendering(False)
                continue
            if not active_frame:
                frame = self._mailbox.take_latest()
                if frame is not None:
                    slot_index, frame_item = frame
                    _sequence, payload = frame_item
                    snapshot, force, active_version = payload
                    try:
                        renderer.request_render(snapshot, force=force)
                        active_frame = True
                        self._set_worker_rendering(True)
                    except Exception as error:
                        self._store_worker_error(error)
                        active_frame = False
                        active_version = None
                        self._set_worker_rendering(False)
                    finally:
                        self._mailbox.release(slot_index)
            if active_frame:
                try:
                    completed = renderer.update_pending(
                        max_regions=RENDER_WORKER_MAX_REGIONS
                    )
                    self._set_worker_rendering(not completed)
                    if completed:
                        active_frame = False
                        self._record_completion(renderer, active_version)
                        active_version = None
                except Exception as error:
                    self._store_worker_error(error)
                    try:
                        renderer.abort_render(release_snapshot=True)
                    except Exception:
                        pass
                    active_frame = False
                    active_version = None
                    self._set_worker_rendering(False)
                _sleep_ms(0)
            else:
                _sleep_ms(1)
        self._stopped = True

    def _execute_control(self, renderer, request):
        """在渲染线程执行一条控制命令并唤醒等待的主线程。"""
        try:
            action = request.action
            arguments = request.arguments
            if action == "preload_style":
                request.result = renderer.preload_style(*arguments)
            elif action == "set_style":
                request.result = renderer.set_style(*arguments)
            elif action == "set_rotation":
                request.result = renderer.set_rotation(*arguments)
            elif action == "abort_render":
                request.result = renderer.abort_render(*arguments)
            elif action == "capture_screen":
                request.result = renderer.capture_screen(*arguments)
            elif action == "record_gc_us":
                request.result = renderer.record_gc_us(*arguments)
            elif action == "set_backlight_brightness":
                request.result = renderer.lcd.set_backlight_brightness(*arguments)
            else:
                raise ValueError("UNKNOWN_RENDER_CONTROL:{}".format(action))
            self._refresh_metadata(renderer)
        except Exception as error:
            request.error = error
        request.completed = True

    def _submit_control(self, action, *arguments):
        """提交同步控制命令，并在超时前返回工作线程执行结果。"""
        if not self._threaded:
            renderer = self._renderer
            if action == "set_backlight_brightness":
                return renderer.lcd.set_backlight_brightness(*arguments)
            method = getattr(renderer, action)
            result = method(*arguments)
            self._refresh_metadata(renderer)
            return result
        request = RenderControlRequest(action, arguments)
        self._control_queue.put(request, RENDER_CONTROL_TIMEOUT_MS)
        deadline = _ticks_add(_ticks_ms(), RENDER_CONTROL_TIMEOUT_MS)
        while not request.completed:
            if self._stopped or _ticks_diff(_ticks_ms(), deadline) >= 0:
                raise RuntimeError("RENDER_CONTROL_EXECUTION_TIMEOUT")
            _sleep_ms(1)
        if request.error is not None:
            raise request.error
        return request.result

    def _refresh_metadata(self, renderer):
        """刷新样式、Canvas 和 LCD 状态等主线程只读缓存。"""
        self._style_name = renderer.style_name()
        self._style_type = renderer.style_type()
        self._canvas_backend = renderer.canvas_backend()
        self._backlight_brightness = renderer.lcd.backlight_brightness()
        self._rotation = renderer.lcd.rotation()

    def _record_completion(self, renderer, frame_version):
        """保存完成帧的性能数据、版本号和完成通知计数。"""
        self._last_render_ms = renderer.last_render_ms()
        self._last_profile = renderer.last_profile()
        self._last_detailed_profile = renderer.last_detailed_profile()
        self._last_completed_version = frame_version
        self._completed_count += 1
        self._set_worker_rendering(False)

    def _set_worker_rendering(self, rendering):
        """更新工作线程是否正在处理已经登记的渲染帧。"""
        self._worker_rendering = bool(rendering)

    def _store_worker_error(self, error):
        """保存异步渲染异常，等待主线程按现有恢复策略处理。"""
        self._worker_error = error

    def _raise_worker_error(self):
        """在主线程重新抛出并清除最近一次异步渲染异常。"""
        error = self._worker_error
        if error is not None:
            self._worker_error = None
            raise error

    def threaded(self):
        """返回当前是否由独立 Python 工作线程推进渲染。"""
        return self._threaded

    def accepts_while_rendering(self):
        """返回当前服务是否允许主线程在渲染期间覆盖待处理帧。"""
        return self._threaded

    def request_render(self, snapshot, force=False, frame_version=None):
        """提交渲染快照；线程模式只保留尚未消费的最新一帧。"""
        if not self._threaded:
            self._active_frame_version = frame_version
            return self._renderer.request_render(snapshot, force=force)
        return self._mailbox.publish(snapshot, force, frame_version)

    def update_pending(self, max_regions=8, time_budget_us=None):
        """同步模式推进区域；线程模式仅消费完成通知并转交异步异常。"""
        if not self._threaded:
            completed = self._renderer.update_pending(
                max_regions=max_regions,
                time_budget_us=time_budget_us,
            )
            if completed:
                self._record_completion(
                    self._renderer, self._active_frame_version
                )
                self._active_frame_version = None
            return completed
        self._raise_worker_error()
        if self._reported_count < self._completed_count:
            self._reported_count = self._completed_count
            return True
        _sleep_ms(0)
        return False

    def is_rendering(self):
        """返回渲染器或双槽邮箱是否仍有帧需要处理。"""
        if not self._threaded:
            return self._renderer.is_rendering()
        return (
            self._worker_rendering
            or self._mailbox.has_pending()
            or self._reported_count < self._completed_count
        )

    def preload_style(self, style_name):
        """在渲染所有者线程预加载指定样式。"""
        return self._submit_control("preload_style", style_name)

    def set_style(self, style_name):
        """丢弃过期待处理帧并在渲染所有者线程切换样式。"""
        if style_name == self._style_name:
            return False
        if self._threaded:
            self._mailbox.discard_pending()
        return self._submit_control("set_style", style_name)

    def set_rotation(self, rotation):
        """在渲染所有者线程切换 LCD 方向。"""
        return self._submit_control("set_rotation", rotation)

    def abort_render(self, release_snapshot=False):
        """丢弃待处理帧并在渲染所有者线程中止当前帧。"""
        if self._threaded:
            self._mailbox.discard_pending()
        return self._submit_control("abort_render", release_snapshot)

    def capture_screen(self, chunk_writer, rows_per_chunk=8):
        """在渲染所有者线程重绘并输出当前屏幕截图。"""
        return self._submit_control(
            "capture_screen", chunk_writer, rows_per_chunk
        )

    def set_backlight_brightness(self, brightness):
        """在渲染所有者线程设置 LCD 背光亮度。"""
        return self._submit_control("set_backlight_brightness", brightness)

    def backlight_brightness(self):
        """返回缓存的 LCD 当前背光亮度。"""
        return self._backlight_brightness

    def rotation(self):
        """返回缓存的 LCD 当前屏幕旋转角度。"""
        return self._rotation

    def record_gc_us(self, elapsed_us):
        """在渲染所有者线程记录安全垃圾回收耗时。"""
        return self._submit_control("record_gc_us", elapsed_us)

    def style_name(self):
        """返回缓存的当前样式名称。"""
        return self._style_name

    def style_type(self):
        """返回缓存的当前样式类型。"""
        return self._style_type

    def canvas_backend(self):
        """返回缓存的 Canvas 后端名称。"""
        return self._canvas_backend

    def last_render_ms(self):
        """返回最近完成帧的总耗时毫秒数。"""
        return self._last_render_ms

    def last_profile(self):
        """返回最近完成帧的 Canvas、LCD 和区域统计。"""
        return self._last_profile

    def last_detailed_profile(self):
        """返回最近完成帧的详细性能统计副本。"""
        return dict(self._last_detailed_profile)

    def last_completed_version(self):
        """返回最近完成渲染帧对应的主线程快照版本。"""
        return self._last_completed_version

    def dropped_frames(self):
        """返回线程模式下被最新快照覆盖的累计帧数。"""
        return self._mailbox.dropped_count() if self._threaded else 0

    def frame_policy(self):
        """返回当前生效的 latest 或 block 新帧背压策略。"""
        return self._frame_policy

    def stop(self, timeout_ms=1000):
        """停止测试或软重启前的渲染工作线程。"""
        if not self._threaded:
            return True
        self._running = False
        deadline = _ticks_add(_ticks_ms(), max(1, int(timeout_ms)))
        while not self._stopped:
            if _ticks_diff(_ticks_ms(), deadline) >= 0:
                return False
            _sleep_ms(1)
        self._threaded = False
        return True
