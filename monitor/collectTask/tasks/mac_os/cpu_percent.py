"""macOS CPU 占用率采样实现。"""

import psutil


class CpuPercentSampler:
    """通过 Darwin 原生 CPU 时间计数器计算各逻辑核心平均占用率。"""

    def __init__(self, logger):
        """保存日志对象，保持各平台采样器构造接口一致。"""
        self.logger = logger

    def sample(self, sample_window_seconds):
        """使用短阻塞采样窗口读取 CPU 占用率，不依赖 Linux procfs。"""
        values = psutil.cpu_percent(interval=sample_window_seconds, percpu=True)
        return sum(values) / len(values) if values else 0.0

