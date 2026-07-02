"""通过操作系统接口采集系统硬件和网络运行指标。"""

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
    """在独立线程中低频探测网络延迟，避免阻塞主采集循环。"""

    def __init__(self, target, interval=5.0):
        """保存探测目标和周期，并初始化线程安全的结果状态。"""
        self.target, self.interval = target, interval
        self.value, self.online = None, False
        self.lock = threading.Lock()

    def start(self):
        """启动守护线程持续执行网络延迟探测。"""
        threading.Thread(target=self._run, name="网络延迟采集", daemon=True).start()

    def snapshot(self):
        """返回最近一次网络延迟和在线状态。"""
        with self.lock:
            return self.value, self.online

    def _run(self):
        """循环执行 Ping 探测并发布最新结果。"""
        while True:
            value = self._probe()
            with self.lock:
                self.value, self.online = value, value is not None
            time.sleep(self.interval)

    def _probe(self):
        """执行一次跨平台 Ping 并解析毫秒延迟。"""
        command = ["ping", "-n", "1", "-w", "1000", self.target] if platform.system() == "Windows" else ["ping", "-c", "1", "-W", "1", self.target]
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=2, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = re.search(r"(?:time|时间)[=<]\s*(\d+(?:\.\d+)?)\s*ms", result.stdout, re.IGNORECASE)
        return round(float(match.group(1)), 1) if result.returncode == 0 and match else (1.0 if result.returncode == 0 else None)


class SystemInformationCollector:
    """采集 CPU、内存、磁盘、网络和温度并生成协议快照。"""

    def __init__(self, ping_target):
        """初始化历史序列、网络计数基线和异步延迟监控器。"""
        self.histories = {name: deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH) for name in ("cpu", "memory", "disk", "upload", "download")}
        self.last_network = self.last_network_time = None
        self.ping_monitor = PingMonitor(ping_target)
        self.ping_monitor.start()
        psutil.cpu_percent(interval=None)

    @staticmethod
    def _cpu_temperature():
        """从系统温度传感器中选择有效的最高 CPU 温度。"""
        try:
            sensors = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        values = [float(item.current) for name in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal") for item in sensors.get(name, ()) if item.current is not None and 0 < float(item.current) < 150]
        return round(max(values), 1) if values else None

    @staticmethod
    def _local_ip():
        """通过无数据 UDP 路由查询获得首选本机地址。"""
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.connect(("8.8.8.8", 80))
            return connection.getsockname()[0]
        except OSError:
            return "0.0.0.0"
        finally:
            connection.close()

    def _network_rates(self):
        """根据相邻系统网络计数器计算每秒上传和下载字节数。"""
        current, now = psutil.net_io_counters(), time.monotonic()
        upload = download = 0.0
        if self.last_network is not None:
            elapsed = max(0.001, now - self.last_network_time)
            upload = max(0.0, (current.bytes_sent - self.last_network.bytes_sent) / elapsed)
            download = max(0.0, (current.bytes_recv - self.last_network.bytes_recv) / elapsed)
        self.last_network, self.last_network_time = current, now
        return round(upload), round(download)

    @staticmethod
    def _disk_usage():
        """汇总所有有效本地磁盘分区的已用空间和总空间。"""
        total_bytes = 0
        used_bytes = 0
        visited_devices = set()
        for partition in psutil.disk_partitions(all=False):
            options = set(str(partition.opts).lower().split(","))
            if "cdrom" in options:
                continue
            device_key = os.path.normcase(partition.device or partition.mountpoint)
            if device_key in visited_devices:
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (OSError, PermissionError):
                continue
            if usage.total <= 0:
                continue
            visited_devices.add(device_key)
            total_bytes += int(usage.total)
            used_bytes += int(usage.used)
        if total_bytes <= 0:
            usage = psutil.disk_usage(os.path.abspath(os.sep))
            total_bytes, used_bytes = int(usage.total), int(usage.used)
        percent = used_bytes * 100 / total_bytes if total_bytes else 0
        return used_bytes, total_bytes, round(percent, 1)

    def collect(self):
        """采集一次完整系统状态并更新全部历史趋势序列。"""
        cpu, memory = round(psutil.cpu_percent(interval=None), 1), psutil.virtual_memory()
        disk_used, disk_total, disk_percent = self._disk_usage()
        network = self._network_rates()
        ping, online = self.ping_monitor.snapshot()
        for name, value in (("cpu", cpu), ("memory", memory.percent), ("disk", disk_percent), ("upload", network[0]), ("download", network[1])):
            self.histories[name].append(round(value, 1))
        return {"version": 1, "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "host": socket.gethostname(), "platform": platform.system(), "uptime_seconds": max(0, int(time.time() - psutil.boot_time())), "cpu": {"percent": cpu, "temperature_c": self._cpu_temperature(), "history": list(self.histories["cpu"])}, "memory": {"percent": round(memory.percent, 1), "used_bytes": memory.used, "total_bytes": memory.total, "history": list(self.histories["memory"])}, "disk": {"percent": disk_percent, "used_bytes": disk_used, "total_bytes": disk_total, "history": list(self.histories["disk"])}, "network": {"upload_bps": network[0], "download_bps": network[1], "upload_history": list(self.histories["upload"]), "download_history": list(self.histories["download"]), "ping_ms": ping, "online": online, "ip": self._local_ip()}}
