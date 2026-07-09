"""Linux CPU 占用率采样实现。"""

import psutil


class CpuPercentSampler:
    """使用 psutil 读取 Linux 每个逻辑核心占用率并计算平均值。"""

    def __init__(self, logger):
        """保存日志对象，便于平台实现保持统一构造接口。"""
        self.logger = logger

    def sample(self, sample_window_seconds):
        """使用 psutil 阻塞采样窗口返回每核心平均 CPU 占用率。"""
        values = psutil.cpu_percent(interval=sample_window_seconds, percpu=True)
        return sum(values) / len(values) if values else 0.0
