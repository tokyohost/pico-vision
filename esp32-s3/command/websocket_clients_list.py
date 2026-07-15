"""实现 WebSocket 客户端连接记录查询命令。"""

from command.base import CommandStrategy


class WebSocketClientsListCommand(CommandStrategy):
    """返回设备记录的 WebSocket 客户端及当前活动状态。"""

    name = "websocket.clients.list"

    def execute(self, params, context):
        """查询 WebSocket 传输服务中的客户端清单。"""
        del params
        transport = context.service("transport")
        websocket = transport.websocket_transport()
        if websocket is None:
            return {"clients": []}
        return {"clients": websocket.list_clients()}


COMMAND_STRATEGY = WebSocketClientsListCommand()
