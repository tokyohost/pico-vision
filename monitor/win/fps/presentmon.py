"""Low-overhead consumer for the official PresentMon ETW console application."""

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

from .foreground import foreground_process_id


LOGGER = logging.getLogger("pico-monitor")


def _application_root():
    """Return the directory containing bundled files in source and PyInstaller builds."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def find_presentmon():
    """Find an explicitly configured, bundled, installed, or PATH PresentMon binary."""
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
    """Stream frame events from PresentMon and expose a one-second FPS snapshot."""

    def __init__(self, executable=None, window_seconds=1.0, stale_seconds=2.5, clock=time.monotonic):
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

    @staticmethod
    def command(executable):
        """Build a frame-only capture command without files or expensive timing providers."""
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
        """Start the ETW consumer on a daemon thread."""
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._run, name="PresentMon FPS 采集", daemon=True).start()

    def close(self):
        """Stop the child process without blocking application shutdown."""
        self.running = False
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    @staticmethod
    def _field(row, *names):
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for name in names:
            value = lowered.get(name.lower())
            if value not in (None, ""):
                return value
        return None

    def consume_csv_line(self, header, line, received_at=None):
        """Parse one PresentMon CSV row; public for deterministic unit testing."""
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
        return True

    def _prune_locked(self, now):
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
        """Return FPS for the foreground process's busiest swap chain."""
        now = self.clock()
        target_pid = foreground_process_id()
        with self.lock:
            self._prune_locked(now)
            cutoff = now - self.window_seconds
            counts = []
            for (process_id, swap_chain), timestamps in self.events.items():
                count = sum(timestamp >= cutoff for timestamp in timestamps)
                if count:
                    counts.append((count, process_id, swap_chain))
            if not counts:
                return None
            process_counts = [item for item in counts if item[1] == target_pid]
            if target_pid is not None and not process_counts:
                return None
            count, process_id, _ = max(process_counts or counts)
            return {
                "value": round(count / self.window_seconds, 1),
                "source": "presentmon_etw",
                "process_id": process_id,
                "process_name": self.names.get(process_id, ""),
            }

    def _run(self):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
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
                    continue
                self.consume_csv_line(header, line)
        except OSError as error:
            LOGGER.warning("PresentMon FPS 采集启动失败：%s", error)
        finally:
            self.running = False
            self.process = None
