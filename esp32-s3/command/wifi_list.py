"""实现附近 Wi-Fi 搜索命令。"""

from command.base import CommandStrategy


class WifiListCommand(CommandStrategy):
    """处理 wifi.list 命令并返回按信号强度排序的网络。"""

    name = "wifi.list"

    def execute(self, params, context):
        """扫描附近无线网络并返回不含敏感信息的结果。"""
        wifi = context.service("wifi")
        return {"networks": wifi.scan(), "wifi": wifi.status()}


COMMAND_STRATEGY = WifiListCommand()
