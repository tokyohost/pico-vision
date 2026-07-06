"""低开销消费官方 PresentMon ETW 帧事件。"""

import csv
import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from .foreground import foreground_process_id, process_name, related_process_ids


LOGGER = logging.getLogger("pico-monitor")


def _application_root():
    """返回源码环境或 PyInstaller 环境中的资源根目录。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def find_presentmon():
    """查找显式配置、随包提供或位于 PATH 中的 PresentMon 程序。"""
    candidates = []
    configured = os.getenv("PICO_MONITOR_PRESENTMON")
    if configured:
        candidates.append(Path(configured))
    root = _application_root()
    candidates.extend((
        root / "win" / "fps" / "bin" / "PresentMon.exe",
        root / "PresentMon.exe",
        Path(__file__).resolve().parent / "bin" / "PresentMon.exe",
    ))
    path_binary = shutil.which("PresentMon.exe") or shutil.which("PresentMon")
    if path_binary:
        candidates.append(Path(path_binary))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class PresentMonBackend:
    """流式接收 PresentMon 帧事件并生成一秒窗口的 FPS 快照。"""

    def __init__(self, executable=None, window_seconds=1.0, stale_seconds=2.5, clock=time.monotonic):
        """初始化 PresentMon 路径、采样窗口和事件缓存。"""
        if platform.system() != "Windows" and executable is None:
            raise OSError("PresentMon 仅支持 Windows")
        self.executable = Path(executable) if executable else find_presentmon()
        if self.executable is None:
            raise OSError("未找到 PresentMon.exe")
        self.window_seconds = max(0.5, float(window_seconds))
        self.stale_seconds = max(self.window_seconds, float(stale_seconds))
        self.clock = clock
        self.events = defaultdict(deque)
        self.names = {}
        self.lock = threading.Lock()
        self.process = None
        self.running = False
        self.last_event_time = None
        self.diagnostic_reason = "PresentMon 尚未启动"
        self._header_detected = False
        LOGGER.info("[FPS][PresentMon] 已定位程序：%s", self.executable)

    @staticmethod
    def command(executable):
        """构造仅输出帧事件且不写文件的轻量采集命令。"""
        return [
            str(executable),
            "--output_stdout",
            "--no_console_stats",
            "--no_track_gpu",
            "--no_track_input",
            "--v2_metrics",
            "--session_name", "PicoMonitorFPS",
            "--stop_existing_session",
        ]

    def start(self):
        """在守护线程中启动 ETW 事件消费。"""
        if self.running:
            return
        self.running = True
        self.diagnostic_reason = "PresentMon 正在启动，等待帧事件"
        threading.Thread(target=self._run, name="PresentMon FPS 采集", daemon=True).start()

    def close(self):
        """终止子进程且不阻塞应用退出。"""
        self.running = False
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    @staticmethod
    def _field(row, *names):
        """按不区分大小写的候选名称读取 CSV 字段。"""
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for name in names:
            value = lowered.get(name.lower())
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def _normalized_process_name(value):
        """统一 PresentMon 应用路径与 Windows 进程名的比较格式。"""
        return str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1].lower()

    def consume_csv_line(self, header, line, received_at=None):
        """解析一行 PresentMon CSV 数据，并开放给确定性单元测试使用。"""
        try:
            row = next(csv.DictReader(io.StringIO(line), fieldnames=header))
            process_id = int(self._field(row, "ProcessID", "ProcessId"))
        except (StopIteration, TypeError, ValueError):
            return False
        application = str(self._field(row, "Application", "ProcessName") or "").strip()
        swap_chain = str(self._field(row, "SwapChainAddress") or "default").strip()
        timestamp = self.clock() if received_at is None else float(received_at)
        with self.lock:
            timestamps = self.events[(process_id, swap_chain)]
            timestamps.append(timestamp)
            cutoff = timestamp - self.stale_seconds
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            self.names[process_id] = application
            self.last_event_time = timestamp
            self.diagnostic_reason = "已收到帧事件"
        return True

    def _prune_locked(self, now):
        """在持锁状态下清理超过保留时限的帧事件。"""
        cutoff = now - self.stale_seconds
        empty = []
        for key, timestamps in self.events.items():
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            if not timestamps:
                empty.append(key)
        for key in empty:
            del self.events[key]

    def snapshot(self):
        """返回前台进程最活跃交换链的 FPS。"""
        now = self.clock()
        target_pid = foreground_process_id()
        target_pids = related_process_ids(target_pid)
        target_name = process_name(target_pid)
        with self.lock:
            self._prune_locked(now)
            cutoff = now - self.window_seconds
            counts = []
            for (process_id, swap_chain), timestamps in self.events.items():
                count = sum(timestamp >= cutoff for timestamp in timestamps)
                if count:
                    counts.append((count, process_id, swap_chain))
            if not counts:
                if not self.running:
                    self.diagnostic_reason = "PresentMon 未运行或已经退出"
                elif not self._header_detected:
                    self.diagnostic_reason = "尚未识别 PresentMon CSV 表头"
                elif self.last_event_time is None:
                    self.diagnostic_reason = "已识别表头但尚未收到帧事件"
                else:
                    self.diagnostic_reason = "最近 {:.1f} 秒内没有帧事件".format(self.window_seconds)
                return None
            process_counts = [
                item for item in counts
                if item[1] in target_pids or (
                    target_name
                    and self._normalized_process_name(self.names.get(item[1])) == target_name
                )
            ]
            if target_pid is not None and not process_counts:
                active_pids = sorted({item[1] for item in counts})
                self.diagnostic_reason = "前台应用 {} 进程树 {} 没有帧事件，当前有帧事件的 PID={}".format(
                    target_name or "未知进程", sorted(target_pids), active_pids
                )
                return None
            count, process_id, _ = max(process_counts or counts)
            self.diagnostic_reason = "采样正常，前台应用={}，前台 PID={}，帧进程 PID={}".format(
                target_name or "未知进程", target_pid, process_id
            )
            return {
                "value": round(count / self.window_seconds, 1),
                "source": "presentmon_etw",
                "process_id": process_id,
                "process_name": self.names.get(process_id, ""),
            }

    def _run(self):
        """运行 PresentMon 子进程并持续消费标准输出。"""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            LOGGER.info("[FPS][PresentMon] 正在启动 ETW 采集：%s", self.executable)
            self.process = subprocess.Popen(
                self.command(self.executable),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            header = None
            for raw_line in self.process.stdout or ():
                if not self.running:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                if header is None:
                    possible = next(csv.reader([line]), [])
                    if "ProcessID" in possible and "Application" in possible:
                        header = possible
                        self._header_detected = True
                        self.diagnostic_reason = "已识别表头，等待帧事件"
                        LOGGER.info("[FPS][PresentMon] CSV 表头识别成功，字段数=%d", len(header))
                    continue
                self.consume_csv_line(header, line)
        except OSError as error:
            self.diagnostic_reason = "PresentMon 启动失败：{}".format(error)
            LOGGER.warning("PresentMon FPS 采集启动失败：%s", error)
        finally:
            exit_code = self.process.poll() if self.process is not None else None
            if self.running:
                self.diagnostic_reason = "PresentMon 意外退出，退出码={}".format(exit_code)
                LOGGER.warning("[FPS][PresentMon] 采集进程退出，退出码=%s", exit_code)
            self.running = False
            self.process = None
