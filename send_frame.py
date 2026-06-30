#!/usr/bin/env python3
"""采集系统状态，并通过 USB 串口向 Pico 发送 JSON 快照。"""

import argparse
import datetime as dt
import json
import os
import platform
import re
import socket
import struct
import subprocess
import threading
import time
from collections import deque

import psutil
import serial
from serial.tools import list_ports


PING_COMMAND = b"PING:PICO_LCD?\n"
EXPECTED_PREFIX = "PONG:PICO_LCD:"
JSON_MAGIC = b"JSN0"
SERIAL_BAUDRATE = 115200
SEND_INTERVAL_SECONDS = 0.5
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
        self.thread = threading.Thread(target=self._run, name="网络延迟采集", daemon=True)
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
        match = re.search(r"(?:time|时间)[=<]\s*(\d+(?:\.\d+)?)\s*ms", result.stdout, re.IGNORECASE)
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
        preferred = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal")
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
            upload = max(0.0, (current.bytes_sent - self.last_network.bytes_sent) / elapsed)
            download = max(0.0, (current.bytes_recv - self.last_network.bytes_recv) / elapsed)
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


class PicoJsonClient:
    """发现 Pico LCD 串口设备并发送长度前缀 JSON 数据包。"""

    def __init__(self, configured_port=None):
        """保存可选固定串口，连接将在首次调用时建立。"""
        self.configured_port = configured_port
        self.serial = None

    def connect(self):
        """连接指定串口或通过握手自动发现 Pico LCD。"""
        candidates = [self.configured_port] if self.configured_port else [item.device for item in list_ports.comports()]
        for port in candidates:
            device = self._try_port(port)
            if device is not None:
                self.serial = device
                print("已连接 Pico LCD：{}".format(port))
                return
        raise RuntimeError("未找到 Pico LCD，请确认 main.py 已在 Pico 运行且串口未被占用。")

    @staticmethod
    def _try_port(port):
        """打开单个串口并通过文本握手验证设备身份。"""
        try:
            device = serial.Serial(port, SERIAL_BAUDRATE, timeout=0.3, write_timeout=2)
            time.sleep(1.5)
            device.reset_input_buffer()
            device.reset_output_buffer()
            for _ in range(3):
                device.write(PING_COMMAND)
                device.flush()
                deadline = time.monotonic() + 1.2
                while time.monotonic() < deadline:
                    line = device.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith(EXPECTED_PREFIX) and line.endswith(":JSON"):
                        return device
            device.close()
        except (OSError, serial.SerialException):
            return None
        return None

    def send(self, snapshot):
        """将系统快照编码为紧凑 UTF-8 JSON 后发送给 Pico。"""
        if self.serial is None:
            raise RuntimeError("Pico 串口尚未连接。")
        payload = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        packet = JSON_MAGIC + struct.pack(">I", len(payload)) + payload
        self.serial.write(packet)
        self.serial.flush()

    def close(self):
        """安全关闭当前串口连接。"""
        if self.serial is not None:
            self.serial.close()
            self.serial = None


def create_argument_parser():
    """创建系统采集程序的命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="向 Pico LCD 发送系统状态 JSON")
    parser.add_argument("--port", help="固定串口名称；省略时自动发现")
    parser.add_argument("--ping-target", default="www.baidu.com", help="网络延迟检测目标")
    parser.add_argument("--interval", type=float, default=SEND_INTERVAL_SECONDS,
                        help="JSON 发送间隔，单位为秒，默认 0.5")
    parser.add_argument("--once", action="store_true", help="仅发送一次，便于协议调试")
    return parser


def main():
    """持续采集系统信息，并按配置周期发送最新 JSON 快照。"""
    arguments = create_argument_parser().parse_args()
    if arguments.interval <= 0:
        raise SystemExit("--interval 必须大于 0")
    collector = SystemInformationCollector(arguments.ping_target)
    client = PicoJsonClient(arguments.port)
    client.connect()
    try:
        while True:
            started = time.monotonic()
            snapshot = collector.collect()
            client.send(snapshot)
            print("已发送 {} | CPU {}% | 内存 {}%".format(
                snapshot["timestamp"], snapshot["cpu"]["percent"], snapshot["memory"]["percent"]))
            if arguments.once:
                break
            time.sleep(max(0.0, arguments.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("已停止系统状态发送。")
    finally:
        client.close()


if __name__ == "__main__":
    main()
