"""在电脑端采集系统资源、网络速率和延迟信息。"""

import datetime as dt
import os
import platform
import re
import socket
import subprocess
import threading
import time
from collections import deque

import psutil


HISTORY_LENGTH = 24


class PingMonitor:
    """在独立线程中低频检测网络延迟，避免阻塞系统快照采集。"""

    def __init__(self, target, interval=5.0):
        """保存检测目标、执行间隔和线程共享状态。"""
        self.target = target
        self.interval = interval
        self.value = None
        self.online = False
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        """启动唯一的后台网络延迟检测线程。"""
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(
            target=self._run,
            name="网络延迟采集",
            daemon=True,
        )
        self.thread.start()

    def get_snapshot(self):
        """返回最近一次完成的网络延迟检测结果。"""
        with self.lock:
            return self.value, self.online

    def _run(self):
        """持续检测目标主机并发布最新延迟。"""
        while True:
            value = self._probe()
            with self.lock:
                self.value = value
                self.online = value is not None
            time.sleep(self.interval)

    def _probe(self):
        """执行一次跨平台 Ping 并解析毫秒延迟。"""
        if platform.system() == "Windows":
            command = ["ping", "-n", "1", "-w", "1000", self.target]
        else:
            command = ["ping", "-c", "1", "-W", "1", self.target]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=2,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        match = re.search(
            r"(?:time|时间)[=<]\s*(\d+(?:\.\d+)?)\s*ms",
            result.stdout,
            re.IGNORECASE,
        )
        return round(float(match.group(1)), 1) if match else 1.0


class SystemInformationCollector:
    """在系统端采集资源指标，并生成可序列化的结构化快照。"""

    def __init__(self, ping_target):
        """初始化历史序列、网络采样基准和 Ping 监控器。"""
        self.cpu_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.memory_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.disk_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.upload_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.download_history = deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH)
        self.last_network = None
        self.last_network_time = None
        self.ping_monitor = PingMonitor(ping_target)
        self.ping_monitor.start()
        psutil.cpu_percent(interval=None)

    @staticmethod
    def _cpu_temperature():
        """从 psutil 温度传感器中选择可信的 CPU 温度。"""
        try:
            sensors = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        preferred = (
            "coretemp",
            "k10temp",
            "zenpower",
            "cpu_thermal",
            "soc_thermal",
        )
        values = []
        for name in preferred:
            for entry in sensors.get(name, ()):
                try:
                    value = float(entry.current)
                except (TypeError, ValueError):
                    continue
                if 0 < value < 150:
                    values.append(value)
        if not values:
            return None
        return round(max(values), 1)

    @staticmethod
    def _local_ip():
        """通过无数据 UDP 套接字获取当前首选本机地址。"""
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
        except OSError:
            return "0.0.0.0"
        finally:
            connection.close()

    def _network_rates(self):
        """根据相邻采样计算每秒上传和下载字节数。"""
        current = psutil.net_io_counters()
        now = time.monotonic()
        upload = 0.0
        download = 0.0
        if self.last_network is not None and self.last_network_time is not None:
            elapsed = max(0.001, now - self.last_network_time)
            upload = max(
                0.0,
                (current.bytes_sent - self.last_network.bytes_sent) / elapsed,
            )
            download = max(
                0.0,
                (current.bytes_recv - self.last_network.bytes_recv) / elapsed,
            )
        self.last_network = current
        self.last_network_time = now
        return round(upload), round(download)

    def collect(self):
        """采集一次完整系统状态并更新所有历史序列。"""
        cpu_percent = round(psutil.cpu_percent(interval=None), 1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        upload, download = self._network_rates()
        ping_ms, online = self.ping_monitor.get_snapshot()

        self.cpu_history.append(cpu_percent)
        self.memory_history.append(round(memory.percent, 1))
        self.disk_history.append(round(disk.percent, 1))
        self.upload_history.append(upload)
        self.download_history.append(download)

        return {
            "version": 1,
            "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "host": socket.gethostname(),
            "platform": platform.system(),
            "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
            "cpu": {
                "percent": cpu_percent,
                "temperature_c": self._cpu_temperature(),
                "history": list(self.cpu_history),
            },
            "memory": {
                "percent": round(memory.percent, 1),
                "used_bytes": memory.used,
                "total_bytes": memory.total,
                "history": list(self.memory_history),
            },
            "disk": {
                "percent": round(disk.percent, 1),
                "used_bytes": disk.used,
                "total_bytes": disk.total,
                "history": list(self.disk_history),
            },
            "network": {
                "upload_bps": upload,
                "download_bps": download,
                "upload_history": list(self.upload_history),
                "download_history": list(self.download_history),
                "ping_ms": ping_ms,
                "online": online,
                "ip": self._local_ip(),
            },
        }
