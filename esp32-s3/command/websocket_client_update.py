"""实现 WebSocket 客户端启用状态和优先级更新命令。"""

from command.base import CommandError, CommandStrategy


class WebSocketClientUpdateCommand(CommandStrategy):
    """校验并更新指定 WebSocket 客户端的连接策略。"""

    name = "websocket.client.update"

    def execute(self, params, context):
        """应用启用状态或优先级，并返回更新后的客户端记录。"""
        client_id = params.get("id")
        if not isinstance(client_id, str) or not client_id.strip():
            raise CommandError("WEBSOCKET_CLIENT_ID_REQUIRED")
        if "enabled" not in params and "priority" not in params:
            raise CommandError("WEBSOCKET_CLIENT_POLICY_REQUIRED")
        transport = context.service("transport")
        websocket = transport.websocket_transport()
        if websocket is None:
            raise CommandError("WEBSOCKET_SERVICE_UNAVAILABLE")
        try:
            return websocket.update_client(
                client_id.strip(),
                params.get("enabled") if "enabled" in params else None,
                params.get("priority") if "priority" in params else None,
            )
        except (KeyError, ValueError) as error:
            raise CommandError(str(error)) from error


COMMAND_STRATEGY = WebSocketClientUpdateCommand()
