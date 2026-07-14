"""实现指定 Wi-Fi 名称和密码的连接命令。"""

from command.base import CommandError, CommandStrategy


class WifiSetCommand(CommandStrategy):
    """处理 wifi.set 命令并明确返回连接成功或失败。"""

    name = "wifi.set"

    def execute(self, params, context):
        """校验 Wi-Fi 参数，连接网络并返回获得的网络详情。"""
        ssid = params.get("ssid")
        password = params.get("password", "")
        timeout_ms = params.get("timeout_ms", 15000)
        if not isinstance(ssid, str) or not ssid.strip():
            raise CommandError("WIFI_SSID_REQUIRED")
        if not isinstance(password, str):
            raise CommandError("WIFI_PASSWORD_MUST_BE_STRING")
        try:
            timeout_ms = max(1000, min(60000, int(timeout_ms)))
            status = context.service("wifi").connect(ssid, password, timeout_ms)
        except (OSError, RuntimeError, ValueError) as error:
            raise CommandError("WIFI_CONNECT_FAILED:{}".format(error))
        return {"connected": True, "wifi": status}


COMMAND_STRATEGY = WifiSetCommand()
