"""提供 Linux NAS 通用的 proc CPU 占用率采样器。"""

import time


class ProcStatCpuPercentSampler:
    """使用 /proc/stat 前后两次快照计算 NAS CPU 总占用率。"""

    def __init__(self, logger, stat_path="/proc/stat"):
        """保存日志对象和 CPU 统计文件路径。"""
        self.logger = logger
        self.stat_path = stat_path

    def sample(self, sample_window_seconds):
        """在指定采样窗口内计算 CPU 非空闲时间占比。"""
        first = self._read_cpu_times()
        time.sleep(max(0.0, float(sample_window_seconds)))
        second = self._read_cpu_times()
        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta))

    def _read_cpu_times(self):
        """读取 /proc/stat 汇总行并返回总时间和空闲时间。"""
        with open(self.stat_path, "r", encoding="ascii") as stat_file:
            fields = stat_file.readline().split()
        if not fields or fields[0] != "cpu" or len(fields) < 5:
            raise OSError("NAS CPU 统计文件格式无效")
        values = [int(value) for value in fields[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
