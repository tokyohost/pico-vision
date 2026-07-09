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

"""编排各领域采集器并生成 Pico 协议系统快照。"""

import datetime as dt
import platform
import socket
import time
from collections import deque

import psutil

from constants import HISTORY_LENGTH
from history import update_per_second
from monitor_core.collectors.cpu import CpuMetricsMixin
from monitor_core.collectors.disk import DiskMetricsMixin
from monitor_core.collectors.gpu import GpuMonitor
from monitor_core.collectors.models import LOGGER, SENSOR_HOST_PRIORITY_TTL_SECONDS
from monitor_core.collectors.network import NetworkMetricsMixin, PingMonitor
from monitor_core.collectors.power import PowerMonitor

try:
    from win.fps import FpsMonitor
except (ImportError, OSError):
    FpsMonitor = None

try:
    from win.sensor_host import DEFAULT_PIPE_NAME as SENSOR_HOST_DEFAULT_PIPE_NAME
    from win.sensor_host import SensorHostManager
except (ImportError, OSError):
    SENSOR_HOST_DEFAULT_PIPE_NAME = "omniwatch.sensorhost"
    SensorHostManager = None


class SystemInformationCollector(DiskMetricsMixin, NetworkMetricsMixin, CpuMetricsMixin):
    """采集 CPU、内存、磁盘、网络、温度和功耗并生成协议快照。"""

    _windows_cpu_frequency_sampler = None
    _windows_cpu_frequency_sampler_unavailable = False
    _windows_cpu_frequency_source_logged = False

    def __init__(self, ping_target, sensor_host_enabled=True, sensor_host_path=None, sensor_host_pipe=SENSOR_HOST_DEFAULT_PIPE_NAME):
        """初始化历史序列、网络计数基线、异步延迟监控器和外置传感器宿主。"""
        self.histories = {name: deque([0] * HISTORY_LENGTH, maxlen=HISTORY_LENGTH) for name in ("cpu", "memory", "upload", "download")}
        self.gpu_history = deque(maxlen=HISTORY_LENGTH)
        self.power_history = deque(maxlen=HISTORY_LENGTH)
        self.history_states = {}
        self.last_network = self.last_network_time = None
        self.last_network_interface = None
        self.last_disk_io = None
        self.last_disk_io_time = None
        self.disk_io_histories = {}
        self.ping_monitor = PingMonitor(ping_target)
        self.power_monitor = PowerMonitor()
        self.gpu_monitor = GpuMonitor()
        self.fps_monitor = FpsMonitor(HISTORY_LENGTH) if FpsMonitor is not None else None
        self.sensor_host = self._create_sensor_host(sensor_host_enabled, sensor_host_path, sensor_host_pipe)
        self.sensor_host_metric_expirations = {}
        self.last_gpu_version = -1
        self.disk_temperature_cache = {}
        self.disk_temperature_time = 0.0
        self.disk_health_cache = {}
        self.disk_health_time = 0.0
        self.disk_hardware_signature = None
        self.ping_monitor.start()
        if self.sensor_host is not None:
            self.sensor_host.start()
        self.gpu_monitor.start()
        if self.fps_monitor is not None:
            self.fps_monitor.start()
        psutil.cpu_percent(interval=None)

    def close(self):
        """关闭指标采集器持有的 SensorHost、FPS 外部进程、GPU 后端和 Windows PDH 查询。"""
        if self.sensor_host is not None:
            self.sensor_host.close()
            self.sensor_host = None
        if self.fps_monitor is not None:
            self.fps_monitor.close()
        backend = self.gpu_monitor.backend
        if backend is not None:
            backend.close()
            self.gpu_monitor.backend = None
        type(self)._close_windows_cpu_frequency_sampler()

    @staticmethod
    def _create_sensor_host(enabled, executable_path, pipe_name):
        """按平台和配置创建 SensorHost 管理器。"""
        if not enabled or platform.system() != "Windows" or SensorHostManager is None:
            return None
        return SensorHostManager(executable_path, pipe_name)

    def mark_sensor_host_metric_available(self, metric_name, now=None):
        """标记指定指标最近由 SensorHost 成功提供，供降级采集任务避让。"""
        now = time.monotonic() if now is None else now
        self.sensor_host_metric_expirations[str(metric_name)] = now + SENSOR_HOST_PRIORITY_TTL_SECONDS

    def is_sensor_host_metric_available(self, metric_name, now=None):
        """判断指定指标是否仍处于 SensorHost 优先窗口内。"""
        now = time.monotonic() if now is None else now
        return self.sensor_host_metric_expirations.get(str(metric_name), 0.0) > now

    def collect(self):
        """采集一次完整系统状态并更新全部历史趋势序列。"""
        collection_started = time.monotonic()
        stage_times = {}
        stage_started = time.monotonic()
        cpu, memory = round(psutil.cpu_percent(interval=None), 1), psutil.virtual_memory()
        stage_times["CPU与内存"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        self._refresh_disk_hardware_state()
        disks = self._disk_rates(self._disk_details())
        physical_disks = self._physical_disk_statistics(disks)
        disk_used, disk_total, disk_percent = self._disk_usage(disks)
        stage_times["磁盘"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        local_ip = self._local_ip()
        network = self._network_rates(local_ip)
        stage_times["网络"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        power = self.power_monitor.snapshot()
        stage_times["电源"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        gpu, gpu_version = self.gpu_monitor.snapshot()
        stage_times["GPU"] = time.monotonic() - stage_started
        gpu_percent = gpu.get("percent") if gpu is not None else None
        history_now = time.monotonic()
        stage_started = time.monotonic()
        fps = self.fps_monitor.snapshot(history_now) if self.fps_monitor is not None else {
            "value": None,
            "history": [0] * HISTORY_LENGTH,
            "source": "unavailable",
            "process_id": None,
            "process_name": "",
        }
        stage_times["FPS"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        ping, online = self.ping_monitor.snapshot()
        stage_times["Ping"] = time.monotonic() - stage_started
        for name, value in (("cpu", cpu), ("memory", memory.percent), ("upload", network[0]), ("download", network[1])):
            update_per_second(
                self.histories[name],
                round(value, 1),
                self.history_states.setdefault(name, {}),
                history_now,
            )
        if power["watts"] is not None:
            update_per_second(
                self.power_history,
                power["watts"],
                self.history_states.setdefault("power", {}),
                history_now,
            )
        if gpu_percent is not None and gpu_version != self.last_gpu_version:
            update_per_second(
                self.gpu_history,
                gpu_percent,
                self.history_states.setdefault("gpu", {}),
                history_now,
            )
        self.last_gpu_version = gpu_version
        power["history"] = list(self.power_history)
        if gpu is not None:
            gpu = dict(gpu)
            gpu["history"] = list(self.gpu_history)
        stage_started = time.monotonic()
        cpu_frequency = self._cpu_frequency_ghz()
        stage_times["CPU频率"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        cpu_temperature = self._cpu_temperature()
        stage_times["CPU温度"] = time.monotonic() - stage_started
        stage_started = time.monotonic()
        link_speed = self._network_link_speed(local_ip)
        stage_times["网卡速率"] = time.monotonic() - stage_started
        total_elapsed = time.monotonic() - collection_started
        ordered_times = sorted(stage_times.items(), key=lambda item: item[1], reverse=True)
        log_method = LOGGER.warning if total_elapsed > 0.5 else LOGGER.debug
        log_method(
            "系统指标分项耗时：总计=%.3f秒，%s；最慢项=%s(%.3f秒)",
            total_elapsed,
            "，".join("{}={:.3f}秒".format(name, elapsed) for name, elapsed in ordered_times),
            ordered_times[0][0],
            ordered_times[0][1],
        )
        return {"version": 1, "timestamp": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "host": socket.gethostname(), "platform": platform.system(), "uptime_seconds": max(0, int(time.time() - psutil.boot_time())), "cpu": {"percent": cpu, "frequency_ghz": cpu_frequency, "temperature_c": cpu_temperature, "history": list(self.histories["cpu"])}, "memory": {"percent": round(memory.percent, 1), "used_bytes": memory.used, "total_bytes": memory.total, "history": list(self.histories["memory"])}, "disk": {"percent": disk_percent, "used_bytes": disk_used, "total_bytes": disk_total}, "disks": disks, "physical_disks": physical_disks, "gpu": gpu, "fps": fps, "power": power, "network": {"upload_bps": network[0], "download_bps": network[1], "transmit_bytes": network[2], "receive_bytes": network[3], "link_speed_mbps": link_speed, "upload_history": list(self.histories["upload"]), "download_history": list(self.histories["download"]), "ping_ms": ping, "online": online, "ip": local_ip}}

