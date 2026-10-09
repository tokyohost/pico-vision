"""将 macOS 后端接入调度任务与旧版完整快照采集入口。"""

import re
import threading

from monitor_core.collectors.network import PingMonitor
from .native import run_command


class MacOsPingMonitor(PingMonitor):
    """使用 Darwin 毫秒超时参数探测延迟，并支持正常关闭。"""

    def __init__(self, target, interval=5.0):
        """保存探测目标并初始化可中断等待事件。"""
        super().__init__(target, interval)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        """创建并保存单个延迟采样线程。"""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="macOS 网络延迟采集", daemon=True)
            self._thread.start()

    def close(self):
        """停止探测并有界等待当前 Ping 命令返回。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _run(self):
        """发布探测结果，通过事件等待实现可中断周期。"""
        while not self._stop.is_set():
            value = self._probe()
            self._result = (value, value is not None)
            self._stop.wait(self.interval)

    def _probe(self):
        """执行 Darwin Ping，其 -W 单位是毫秒，与 Linux 不同。"""
        target = str(self.target)
        if target.startswith("-"):
            return None
        result = run_command(["/sbin/ping", "-n", "-c", "1", "-W", "1000", target], timeout=2)
        if result is None or result.returncode != 0:
            return None
        match = re.search(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", result.stdout.decode("utf-8", "replace"), re.IGNORECASE)
        return round(float(match.group(1)), 1) if match else None


class MacOsGpuMonitor:
    """用现有 GPU Monitor 接口暴露共享 macOS 遥测。"""

    def __init__(self, telemetry):
        """保存共享遥测，不建立重复 GPU 采样线程。"""
        self.telemetry = telemetry
        self.backend = None

    def start(self):
        """启动共享遥测线程，重复启动由遥测对象忽略。"""
        self.telemetry.start()

    def snapshot(self):
        """返回 GPU 快照与版本号，沿用历史曲线去重契约。"""
        sample, version = self.telemetry.snapshot()
        return sample["gpu"], version


class MacOsPowerMonitor:
    """用现有 Power Monitor 接口暴露共享 macOS 功耗。"""

    def __init__(self, telemetry):
        """保存遥测，使 CPU 温度、GPU 和功耗复用一轮采样。"""
        self.telemetry = telemetry

    def snapshot(self):
        """返回瓦数、来源、统计范围与不可用原因。"""
        sample, _ = self.telemetry.snapshot()
        return sample["power"]


class MacOsMetricsMixin:
    """委派 macOS 磁盘辅助指标，其他系统保留原实现。"""

    def _disk_details(self):
        """macOS 使用 APFS 后端，其他平台继续调用原实现。"""
        if getattr(self, "mac_telemetry", None) is not None:
            return self.mac_disk.details()
        return super()._disk_details()

    def _disk_rates(self, disks):
        """macOS 使用物理 diskN 计数器，避免 Linux 磁盘名规则误匹配。"""
        if getattr(self, "mac_telemetry", None) is not None:
            return self.mac_disk.rates(disks)
        return super()._disk_rates(disks)
