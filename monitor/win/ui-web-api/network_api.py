"""Web 界面的 Wi-Fi 和 WebSocket 客户端管理接口。"""

from ..ui.wifi_window import (
    merge_wifi_networks,
    wifi_security_label,
    wifi_state_label,
)


class NetworkApiMixin:
    """处理设备网络连接和 WebSocket 客户端策略。"""

    __slots__ = ()

    def _wifi_list(self, payload):
        """扫描并返回设备附近 Wi-Fi 列表。"""
        del payload
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_list():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 22, "list"
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        networks = merge_wifi_networks(data.get("networks"), data.get("wifi"))
        for network in networks:
            network["state_label"] = wifi_state_label(network)
            network["security_label"] = wifi_security_label(
                network.get("security")
            )
        return {
            "action": "list",
            "networks": networks,
            "wifi": data.get("wifi") or {},
        }

    def _wifi_connect(self, payload):
        """请求设备连接指定 Wi-Fi。"""
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_connect(
            str(payload.get("ssid") or ""), str(payload.get("password") or "")
        ):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 25, "connect"
        )
        return result.get("data") or {}

    def _wifi_forget(self, payload):
        """请求设备忘记指定 Wi-Fi。"""
        self._drain_queue(self._application.wifi_messages)
        if not self._application._request_wifi_forget(str(payload.get("ssid") or "")):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.wifi_messages, 15, "forget"
        )
        return result.get("data") or {}

    def _websocket_list(self, payload):
        """读取设备保存的 WebSocket 客户端策略。"""
        del payload
        self._drain_queue(self._application.websocket_client_messages)
        if not self._application._request_websocket_client_list():
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.websocket_client_messages, 12, "list"
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        clients = []
        for client in data.get("clients", ()):
            if not isinstance(client, dict) or not client.get("id"):
                continue
            normalized = dict(client)
            normalized["enabled"] = bool(client.get("enabled", True))
            normalized["active"] = bool(client.get("active", False))
            try:
                normalized["priority"] = int(client.get("priority", 0))
            except (TypeError, ValueError):
                normalized["priority"] = 0
            try:
                normalized["connections"] = int(client.get("connections", 0))
            except (TypeError, ValueError):
                normalized["connections"] = 0
            clients.append(normalized)
        return {"action": "list", "clients": clients}

    def _websocket_update(self, payload):
        """更新一个 WebSocket 客户端的启用状态和优先级。"""
        self._drain_queue(self._application.websocket_client_messages)
        if not self._application._request_websocket_client_update(
            payload.get("id"),
            payload.get("enabled"),
            payload.get("priority"),
        ):
            raise RuntimeError("后台监控未运行")
        result = self._wait_worker_result(
            self._application.websocket_client_messages, 12, "update"
        )
        return result.get("data") or {}

