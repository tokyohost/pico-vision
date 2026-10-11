"""采集启用日志的 Metal 应用 FPS，不用显示器刷新率冒充应用帧率。"""

import json
import os
import re
import subprocess
import threading
import time
from collections import deque

from constants import HISTORY_LENGTH
from history import update_per_second
from ...system_tasks import CollectionTask
from .native import number


def parse_metal_hud_message(message):
    """解析显式 FPS、毫秒帧间隔或旧版 HUD 的逐帧间隔与 GPU 耗时对。"""
    text = str(message or "")
    if "metal-hud" not in text.lower():
        return None
    match = re.search(r"\b(?:fps|frame\s*rate)\s*[:=]\s*([\d.]+)", text, re.IGNORECASE)
    if match:
        return number(match.group(1), maximum=1000)
    match = re.search(r"(?:frame|present)[ _-]*interval\s*[:=]\s*([\d.]+)\s*ms", text, re.IGNORECASE)
    if match:
        milliseconds = number(match.group(1), minimum=1, maximum=100000)
        return 1000 / milliseconds if milliseconds else None
    # Apple 旧版排列为首帧号、丢帧数、内存 MB，然后重复帧间隔/GPU 耗时对。
    # 只接受完整纯数值记录，格式改变时留空，不猜测任意日志中的数字。
    record = re.split(r"metal-hud\s*:?\s*", text, flags=re.IGNORECASE, maxsplit=1)[-1]
    if not re.fullmatch(r"[\d.,;\s()\[\]]+", record):
        return None
    values = re.findall(r"\d+(?:\.\d+)?", record)
    if len(values) < 5 or (len(values) - 3) % 2 or not values[0].isdigit() or not values[1].isdigit():
        return None
    intervals = [number(value, minimum=1, maximum=100000) for value in values[3::2]]
    if not intervals or any(value is None for value in intervals):
        return None
    return 1000 * len(intervals) / sum(intervals)


class MacOsFpsMonitor:
    """监听 Metal HUD 实时统一日志，为指定 PID 或最近日志应用维护 FPS。"""

    def __init__(self, history_length=HISTORY_LENGTH):
        """初始化可停止日志进程、过期状态和可选进程过滤条件。"""
        self.history = deque([0] * history_length, maxlen=history_length)
        self._history_state = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._process = None
        self._latest = None
        self._sampled_at = 0.0
        self._reason = "目标 Metal 应用需要启用 HUD 日志；非 Metal 应用不支持"
        pid = os.environ.get("MONITOR_MAC_FPS_PID", "").strip()
        self.target_pid = int(pid) if pid.isdigit() and int(pid) > 0 else None

    def start(self):
        """只启动一次后台监听，不修改应用启动参数或系统偏好。"""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="macOS Metal FPS 采集", daemon=True)
            self._thread.start()

    def close(self):
        """关闭本监控器启动的日志子进程并释放监听线程。"""
        self._stop.set()
        with self._lock:
            self._terminate_process(self._process)
        if self._thread is not None:
            self._thread.join(timeout=2)

    @staticmethod
    def _terminate_process(process):
        """有界终止自有进程，必要时杀死该进程，不执行系统级 pkill。"""
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            except OSError:
                pass

    def snapshot(self, now=None):
        """读取最近三秒内的 FPS，日志中断后及时发布不可用状态。"""
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._latest is None or now - self._sampled_at > 3:
                return {"value": None, "history": [0] * self.history.maxlen, "source": "unavailable",
                        "scope": "metal_logged_application", "process_id": self.target_pid,
                        "process_name": "", "reason": self._reason}
            return dict(self._latest, history=list(self.history))

    def _accept_event(self, event, now=None):
        """校验日志事件并更新历史，切换进程时清除前一个应用的数据。"""
        if not isinstance(event, dict):
            return
        value = parse_metal_hud_message(event.get("eventMessage"))
        pid = event.get("processID", event.get("processIdentifier"))
        if not isinstance(pid, int) or pid <= 0 or value is None or (self.target_pid and pid != self.target_pid):
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            if self._latest is None or self._latest["process_id"] != pid or now - self._sampled_at > 3:
                self.history.clear()
                self.history.extend([0] * self.history.maxlen)
                self._history_state.clear()
            value = round(value, 1)
            update_per_second(self.history, value, self._history_state, now)
            self._latest = {"value": value, "source": "metal_hud", "scope": "metal_logged_application",
                            "process_id": pid, "process_name": os.path.basename(str(event.get("processImagePath", ""))),
                            "reason": ""}
            self._sampled_at = now

    def _run(self):
        """监听 NDJSON 日志，工具退出后退避重试，不阻塞其他指标任务。"""
        command = ["/usr/bin/log", "stream", "--style", "ndjson", "--level", "info", "--predicate",
                   'subsystem == "com.apple.metal.hud" OR eventMessage BEGINSWITH "metal-HUD"']
        while not self._stop.is_set():
            process = None
            try:
                with self._lock:
                    if self._stop.is_set():
                        return
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                               text=True, encoding="utf-8", errors="replace",
                                               env=dict(os.environ, LC_ALL="C", LANG="C"))
                    self._process = process
                for line in process.stdout:
                    if self._stop.is_set():
                        break
                    try:
                        self._accept_event(json.loads(line))
                    except (ValueError, TypeError):
                        continue
                if not self._stop.is_set():
                    self._reason = "Metal HUD 日志监听已退出，请检查系统日志权限与 macOS 版本"
            except OSError:
                self._reason = "无法启动 macOS 统一日志工具"
            finally:
                self._terminate_process(process)
                if process is not None and process.stdout is not None:
                    process.stdout.close()
                with self._lock:
                    self._process = None
            self._stop.wait(30)


class MacOsFpsTask(CollectionTask):
    """发布兼容 Pico 快照结构的 macOS Metal 应用 FPS。"""

    name = "fps"
    zh_name = "FPS采集"
    default_interval = 1.0
    order = 70
    supported_platforms = ("Darwin",)

    def collect(self):
        """读取内存中的日志快照，不在调度线程中执行日志命令。"""
        return {"fps": self.collector.fps_monitor.snapshot(time.monotonic())}
