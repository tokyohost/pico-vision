"""兼容历史导入路径并提供群晖 CPU 占用率采样器。"""

from ..nas_cpu_percent import ProcStatCpuPercentSampler


CpuPercentSampler = ProcStatCpuPercentSampler
