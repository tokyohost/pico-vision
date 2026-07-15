"""持久化 WebSocket 客户端身份、启用状态和连接优先级。"""

import json

MAX_WEBSOCKET_CLIENTS = 32
MAX_WEBSOCKET_CLIENT_REGISTRY_BYTES = 16384


class WebSocketClientRegistry:
    """维护曾连接客户端清单，并为新连接提供准入策略。"""

    def __init__(self, path="websocket_clients.json", maximum_clients=MAX_WEBSOCKET_CLIENTS):
        """绑定客户端记录文件并加载已有配置。"""
        self._path = path
        self._maximum_clients = max(1, int(maximum_clients))
        self._clients = {}
        self._dirty = False
        self._load()

    @staticmethod
    def _normalize_text(value, maximum_length):
        """把身份文本规范为非空、定长的可持久化字符串。"""
        value = str(value or "").strip()
        return value[:maximum_length]

    def _load(self):
        """读取无 BOM UTF-8 JSON；损坏文件按空清单安全恢复。"""
        try:
            with open(self._path, "r", encoding="utf-8") as source:
                serialized = source.read(MAX_WEBSOCKET_CLIENT_REGISTRY_BYTES + 1)
            if len(serialized) > MAX_WEBSOCKET_CLIENT_REGISTRY_BYTES:
                return
            payload = json.loads(serialized)
        except (OSError, ValueError, TypeError):
            return
        clients = payload.get("clients") if isinstance(payload, dict) else None
        if not isinstance(clients, list):
            return
        for item in clients[:self._maximum_clients]:
            if not isinstance(item, dict):
                continue
            client_id = self._normalize_text(item.get("id"), 96)
            if not client_id:
                continue
            try:
                priority = int(item.get("priority", 0))
                connections = max(0, int(item.get("connections", 0)))
            except (TypeError, ValueError):
                continue
            self._clients[client_id] = {
                "id": client_id,
                "name": self._normalize_text(item.get("name"), 64) or client_id,
                "enabled": bool(item.get("enabled", True)),
                "priority": priority,
                "connections": connections,
                "last_peer": self._normalize_text(item.get("last_peer"), 64),
            }

    def _persistent_clients(self):
        """生成不含会话临时字段的客户端持久化快照。"""
        clients = []
        for item in self.list_clients():
            item.pop("active", None)
            clients.append(item)
        return clients

    def _save(self):
        """使用 MicroPython 兼容 JSON 参数原子保存无 BOM 客户端清单。"""
        temporary = self._path + ".tmp"
        payload = {"version": 1, "clients": self._persistent_clients()}
        serialized = json.dumps(payload)
        with open(temporary, "w", encoding="utf-8") as target:
            target.write(serialized)
        try:
            import os

            os.rename(temporary, self._path)
        except OSError:
            try:
                import os

                os.remove(self._path)
            except OSError:
                pass
            import os

            os.rename(temporary, self._path)
        self._dirty = False

    def flush(self):
        """仅在客户端记录发生变化时执行一次持久化写入。"""
        if self._dirty:
            self._save()

    def observe(self, client_id, name, peer):
        """登记一次握手身份，并返回该客户端当前准入配置。"""
        client_id = self._normalize_text(client_id, 96)
        if not client_id:
            raise ValueError("WEBSOCKET_CLIENT_ID_REQUIRED")
        name = self._normalize_text(name, 64) or client_id
        peer = self._normalize_text(peer, 64)
        record = self._clients.get(client_id)
        if record is None:
            if len(self._clients) >= self._maximum_clients:
                raise ValueError("WEBSOCKET_CLIENT_LIMIT_REACHED")
            record = {
                "id": client_id,
                "name": name,
                "enabled": True,
                "priority": 0,
                "connections": 0,
                "last_peer": peer,
            }
            self._clients[client_id] = record
            self._dirty = True
        elif record["name"] != name or record.get("last_peer") != peer:
            record["name"] = name
            record["last_peer"] = peer
            self._dirty = True
        return dict(record)

    def record_connected(self, client_id, peer):
        """在连接获准后累计成功连接次数并记录最近地址。"""
        record = self._clients.get(client_id)
        if record is None:
            return
        record["connections"] = int(record.get("connections", 0)) + 1
        record["last_peer"] = self._normalize_text(peer, 64)
        self._dirty = True
        self.flush()

    def update(self, client_id, enabled=None, priority=None):
        """修改指定客户端的启用状态或整数优先级。"""
        client_id = self._normalize_text(client_id, 96)
        record = self._clients.get(client_id)
        if record is None:
            raise KeyError("WEBSOCKET_CLIENT_NOT_FOUND")
        if enabled is not None:
            if not isinstance(enabled, bool):
                raise ValueError("WEBSOCKET_ENABLED_INVALID")
            record["enabled"] = enabled
        if priority is not None:
            try:
                priority = int(priority)
            except (TypeError, ValueError) as error:
                raise ValueError("WEBSOCKET_PRIORITY_INVALID") from error
            if not -1000 <= priority <= 1000:
                raise ValueError("WEBSOCKET_PRIORITY_OUT_OF_RANGE")
            record["priority"] = priority
        self._dirty = True
        self.flush()
        return dict(record)

    def get(self, client_id):
        """返回指定客户端配置，不存在时返回空值。"""
        record = self._clients.get(client_id)
        return dict(record) if record is not None else None

    def list_clients(self, active_client_id=None):
        """返回按优先级和名称排序的客户端独立快照。"""
        clients = []
        for record in self._clients.values():
            item = dict(record)
            item["active"] = item["id"] == active_client_id
            clients.append(item)
        clients.sort(key=lambda item: (-item["priority"], item["name"].lower(), item["id"]))
        return clients
