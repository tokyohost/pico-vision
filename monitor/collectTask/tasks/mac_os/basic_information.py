"""macOS 基础信息采集任务。"""

from ..basic_information import BasicInformationTask as BaseBasicInformationTask


class MacOsBasicInformationTask(BaseBasicInformationTask):
    """在 macOS 上复用统一的基础信息快照、调度和历史序列协议。"""

    supported_platforms = ("Darwin",)

