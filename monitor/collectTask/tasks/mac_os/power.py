"""macOS 功耗采集任务。"""

from ..power import PowerTask as BasePowerTask


class MacOsPowerTask(BasePowerTask):
    """在 macOS 上复用统一的功耗快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

