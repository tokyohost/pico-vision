"""提供忘记设备已保存 Wi-Fi 的命令策略。"""

from command.base import CommandStrategy


class WifiForgetCommand(CommandStrategy):
    """处理 wifi.forget 命令并删除匹配的持久化凭据。"""

    name = "wifi.forget"

    def execute(self, params, context):
        """忘记指定网络并返回清理后的 Wi-Fi 状态。"""
        ssid = params.get("ssid")
        return {"forgotten": ssid, "wifi": context.service("wifi").forget(ssid)}


COMMAND_STRATEGY = WifiForgetCommand()
