"""定义彼此独立、完成后可立即发布结果的系统指标采集子任务。"""

import datetime as dt
import platform
import socket
import time

import psutil

from history import update_per_second
from system_monitor import HISTORY_LENGTH


class CollectionTask:
    """定义采集子任务的运行状态和统一执行接口。"""

    name = "未命名采集任务"

    def __init__(self, collector):
        """保存系统采集器，并把任务初始化为空闲状态。"""
        self.collector = collector
        self.scheduled = False

    def collect(self):
        """采集并返回需要合并到完整快照的顶层字段。"""
        raise NotImplementedError


class CallbackCollectionTask(CollectionTask):
    """把 Monitor 提供的附加采集函数封装为标准采集子任务。"""

    def __init__(self, collector, callback, name):
        """保存附加采集函数和用于日志识别的中文任务名称。"""
        super().__init__(collector)
        self.callback = callback
        self.name = name

    def collect(self):
        """调用附加采集函数并返回顶层快照片段。"""
        return self.callback()


class BasicInformationTask(CollectionTask):
    """采集主机身份、系统平台、时间戳和运行时长。"""

    name = "基础信息采集"

    def collect(self):
        """返回不依赖其他指标的基础快照字段。"""
        return {"version": 1, "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "host": socket.gethostname(), "platform": platform.system(), "uptime_seconds": max(0, int(time.time() - psutil.boot_time()))}


class CpuMemoryTask(CollectionTask):
    """采集 CPU、内存、CPU 频率与温度并维护对应历史序列。"""

    name = "CPU与内存采集"

    def collect(self):
        """返回 CPU 和内存两个顶层指标。"""
        cpu = round(psutil.cpu_percent(interval=None), 1)
        memory = psutil.virtual_memory()
        now = time.monotonic()
        for name, value in (("cpu", cpu), ("memory", memory.percent)):
            update_per_second(self.collector.histories[name], round(value, 1), self.collector.history_states.setdefault(name, {}), now)
        return {
            "cpu": {"percent": cpu, "frequency_ghz": self.collector._cpu_frequency_ghz(), "temperature_c": self.collector._cpu_temperature(), "history": list(self.collector.histories["cpu"])},
            "memory": {"percent": round(memory.percent, 1), "used_bytes": memory.used, "total_bytes": memory.total, "history": list(self.collector.histories["memory"])},
        }


class DiskTask(CollectionTask):
    """采集磁盘容量、健康度、温度和实时读写速率。"""

    name = "磁盘采集"

    def collect(self):
        """返回汇总磁盘、逻辑磁盘和物理磁盘指标。"""
        self.collector._refresh_disk_hardware_state()
        disks = self.collector._disk_rates(self.collector._disk_details())
        used_bytes, total_bytes, percent = self.collector._disk_usage(disks)
        return {"disk": {"percent": percent, "used_bytes": used_bytes, "total_bytes": total_bytes}, "disks": disks, "physical_disks": self.collector._physical_disk_statistics(disks)}


class NetworkTask(CollectionTask):
    """采集主通信网卡、速率、累计流量、IP 和网络延迟。"""

    name = "网络采集"

    def collect(self):
        """返回网络顶层指标并维护上传下载历史序列。"""
        local_ip = self.collector._local_ip()
        network = self.collector._network_rates(local_ip)
        now = time.monotonic()
        for name, value in (("upload", network[0]), ("download", network[1])):
            update_per_second(self.collector.histories[name], round(value, 1), self.collector.history_states.setdefault(name, {}), now)
        ping, online = self.collector.ping_monitor.snapshot()
        return {"network": {"upload_bps": network[0], "download_bps": network[1], "transmit_bytes": network[2], "receive_bytes": network[3], "link_speed_mbps": self.collector._network_link_speed(local_ip), "upload_history": list(self.collector.histories["upload"]), "download_history": list(self.collector.histories["download"]), "ping_ms": ping, "online": online, "ip": local_ip}}


class PowerTask(CollectionTask):
    """采集系统功耗并维护可用功耗的历史序列。"""

    name = "功耗采集"

    def collect(self):
        """返回电源指标和最近功耗历史。"""
        power = self.collector.power_monitor.snapshot()
        if power["watts"] is not None:
            update_per_second(self.collector.power_history, power["watts"], self.collector.history_states.setdefault("power", {}), time.monotonic())
        power["history"] = list(self.collector.power_history)
        return {"power": power}


class GpuTask(CollectionTask):
    """读取 GPU 后台采样结果并维护 GPU 使用率历史。"""

    name = "GPU采集"

    def collect(self):
        """返回最近 GPU 指标；不可用时发布空值。"""
        gpu, version = self.collector.gpu_monitor.snapshot()
        if gpu is None:
            return {"gpu": None}
        gpu = dict(gpu)
        percent = gpu.get("percent")
        if percent is not None and version != self.collector.last_gpu_version:
            update_per_second(self.collector.gpu_history, percent, self.collector.history_states.setdefault("gpu", {}), time.monotonic())
        self.collector.last_gpu_version = version
        gpu["history"] = list(self.collector.gpu_history)
        return {"gpu": gpu}


class FpsTask(CollectionTask):
    """读取前台应用 FPS 后台采样结果。"""

    name = "FPS采集"

    def collect(self):
        """返回 FPS 指标或结构完整的不可用结果。"""
        if self.collector.fps_monitor is None:
            return {"fps": {"value": None, "history": [0] * HISTORY_LENGTH, "source": "unavailable", "process_id": None, "process_name": ""}}
        return {"fps": self.collector.fps_monitor.snapshot(time.monotonic())}


def create_system_tasks(collector):
    """按稳定顺序创建当前完整系统快照所需的全部采集子任务。"""
    return (BasicInformationTask(collector), CpuMemoryTask(collector), DiskTask(collector), NetworkTask(collector), PowerTask(collector), GpuTask(collector), FpsTask(collector))
