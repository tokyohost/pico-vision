"""macOS 网络采集任务。"""

from ..network import NetworkTask as BaseNetworkTask


class MacOsNetworkTask(BaseNetworkTask):
    """在 macOS 上复用统一的网络快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

