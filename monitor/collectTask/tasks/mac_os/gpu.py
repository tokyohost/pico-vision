"""macOS GPU采集任务。"""

from ..gpu import GpuTask as BaseGpuTask


class MacOsGpuTask(BaseGpuTask):
    """在 macOS 上复用统一的GPU快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

