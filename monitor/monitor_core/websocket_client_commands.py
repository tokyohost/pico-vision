"""处理托盘发起的 WebSocket 客户端清单与策略管理任务。"""

import json
import queue

import serial


class WebSocketClientCommandMixin:
    """为监控服务提供串行执行的 WebSocket 客户端管理能力。"""

    def initialize_websocket_client_commands(self):
        """创建客户端管理操作队列。"""
        self.websocket_client_operations = queue.Queue()

    def request_websocket_client_list(self):
        """安排主循环查询设备保存的客户端清单。"""
        self.websocket_client_operations.put(("list", None))

    def request_websocket_client_update(self, payload):
        """校验并安排客户端启用状态或优先级更新。"""
        if not isinstance(payload, dict):
            raise ValueError("WebSocket 客户端策略必须是对象")
        client_id = str(payload.get("id") or "").strip()
        if not client_id:
            raise ValueError("WebSocket 客户端标识不能为空")
        if "enabled" not in payload and "priority" not in payload:
            raise ValueError("必须指定启用状态或优先级")
        operation = {"id": client_id}
        if "enabled" in payload:
            operation["enabled"] = bool(payload["enabled"])
        if "priority" in payload:
            priority = int(payload["priority"])
            if not -1000 <= priority <= 1000:
                raise ValueError("WebSocket 客户端优先级必须在 -1000 至 1000 之间")
            operation["priority"] = priority
        self.websocket_client_operations.put(("update", operation))

    def has_pending_websocket_client_operation(self):
        """返回是否存在待执行的客户端管理任务。"""
        return not self.websocket_client_operations.empty()

    def publish_websocket_client_operation(self):
        """执行一项客户端管理任务并向托盘输出结构化结果。"""
        action, payload = self.websocket_client_operations.get_nowait()
        try:
            if action == "list":
                response = self.client.request_websocket_clients()
            else:
                response = self.client.update_websocket_client(
                    payload["id"],
                    payload.get("enabled") if "enabled" in payload else None,
                    payload.get("priority") if "priority" in payload else None,
                )
            result = {
                "status": "ok",
                "action": action,
                "data": response.get("data") or {},
            }
        except (KeyError, OSError, RuntimeError, serial.SerialException, ValueError) as error:
            result = {"status": "error", "action": action, "message": str(error)}
        print(
            "WEBSOCKET_CLIENT_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
