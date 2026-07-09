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

"""采集网络地址、链路、流量和 Ping 延迟指标。"""

import platform
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil


class PingMonitor:
    """在独立线程中低频探测网络延迟，避免阻塞主采集循环。"""

    def __init__(self, target, interval=5.0):
        """保存探测目标和周期，并初始化可原子替换的结果元组。"""
        self.target, self.interval = target, interval
        self._result = (None, False)

    def start(self):
        """启动守护线程持续执行网络延迟探测。"""
        threading.Thread(target=self._run, name="网络延迟采集", daemon=True).start()

    def snapshot(self):
        """无锁返回最近一次网络延迟和在线状态。"""
        return self._result

    def _run(self):
        """循环执行 Ping 探测并发布最新结果。"""
        while True:
            value = self._probe()
            self._result = (value, value is not None)
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


class NetworkMetricsMixin:
    """为系统采集器提供网络接口选择、流量速率和链路速率能力。"""

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

    @staticmethod
    def _linux_route_interface(destination="8.8.8.8"):
        """通过 Linux rtnetlink 查询指定目标实际使用的出口接口名称。"""
        if platform.system() != "Linux":
            return None
        try:
            from pyroute2 import IPRoute

            with IPRoute() as route:
                results = route.route("get", dst=destination)
                if not results:
                    return None
                attributes = dict(results[0].get("attrs", ()))
                interface_index = results[0].get("oif") or attributes.get("RTA_OIF")
                if not interface_index:
                    return None
                links = route.link("get", index=interface_index)
                if not links:
                    return None
                return dict(links[0].get("attrs", ())).get("IFLA_IFNAME")
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            return None

    @staticmethod
    def _interface_for_ip(local_ip):
        """根据本机 IP 查找承载该地址的活动网络接口。"""
        try:
            addresses = psutil.net_if_addrs()
            statistics = psutil.net_if_stats()
        except (AttributeError, OSError):
            return None
        for interface_name, interface_addresses in addresses.items():
            interface_statistics = statistics.get(interface_name)
            if interface_statistics is None or not interface_statistics.isup:
                continue
            if any(address.address == local_ip for address in interface_addresses):
                return interface_name
        return None

    @staticmethod
    def _linux_interface_bytes(interface_name):
        """从 Linux sysfs 读取指定接口的累计发送与接收字节数。"""
        if not interface_name or platform.system() != "Linux":
            return None
        statistics_path = Path("/sys/class/net") / interface_name / "statistics"
        try:
            transmitted = int((statistics_path / "tx_bytes").read_text(encoding="ascii").strip())
            received = int((statistics_path / "rx_bytes").read_text(encoding="ascii").strip())
            return transmitted, received
        except (OSError, TypeError, ValueError):
            return None

    @classmethod
    def _network_counter(cls, local_ip):
        """返回主通信接口名称及其累计流量，并避免汇总虚拟接口。"""
        interface_name = cls._linux_route_interface() if platform.system() == "Linux" else None
        if not interface_name:
            interface_name = cls._interface_for_ip(local_ip)
        if platform.system() == "Linux":
            values = cls._linux_interface_bytes(interface_name)
            if values is not None:
                return interface_name, values[0], values[1]
        try:
            counters = psutil.net_io_counters(pernic=True) or {}
        except (AttributeError, OSError):
            counters = {}
        counter = counters.get(interface_name)
        if counter is not None:
            return interface_name, int(counter.bytes_sent), int(counter.bytes_recv)
        aggregate = psutil.net_io_counters()
        return None, int(aggregate.bytes_sent), int(aggregate.bytes_recv)

    def _network_rates(self, local_ip):
        """计算主通信接口的实时上传下载速率及累计字节数。"""
        interface_name, bytes_sent, bytes_received = self._network_counter(local_ip)
        current, now = (bytes_sent, bytes_received), time.monotonic()
        upload = download = 0.0
        if self.last_network is not None and interface_name == self.last_network_interface:
            elapsed = max(0.001, now - self.last_network_time)
            upload = max(0.0, (current[0] - self.last_network[0]) / elapsed)
            download = max(0.0, (current[1] - self.last_network[1]) / elapsed)
        self.last_network, self.last_network_time = current, now
        self.last_network_interface = interface_name
        return round(upload), round(download), current[0], current[1]

    @classmethod
    def _network_link_speed(cls, local_ip):
        """按首选本机 IP 查找活动网卡，并返回其协商速率。"""
        try:
            addresses = psutil.net_if_addrs()
            statistics = psutil.net_if_stats()
        except (AttributeError, OSError):
            return 0
        fallback_speed = 0
        for interface_name, interface_addresses in addresses.items():
            interface_statistics = statistics.get(interface_name)
            if interface_statistics is None or not interface_statistics.isup:
                continue
            speed = max(0, int(interface_statistics.speed or 0))
            fallback_speed = max(fallback_speed, speed)
            if any(address.address == local_ip for address in interface_addresses):
                return speed
        return fallback_speed

