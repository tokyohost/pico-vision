"""处理托盘发起的设备 Wi-Fi 扫描与连接任务。"""

import json
import queue

import serial


class WifiCommandMixin:
    """为监控服务提供串行执行的 Wi-Fi 管理能力。"""

    def initialize_wifi_commands(self):
        """初始化 Wi-Fi 操作队列，由监控服务构造函数调用。"""
        self.wifi_operations = queue.Queue()

    def request_wifi_list(self):
        """安排主循环在设备通信空闲时扫描附近无线网络。"""
        self.wifi_operations.put(("list", None))

    def request_wifi_connect(self, payload):
        """校验并安排连接指定无线网络。"""
        if not isinstance(payload, dict):
            raise ValueError("Wi-Fi 连接参数必须是对象")
        ssid = payload.get("ssid")
        password = payload.get("password", "")
        if not isinstance(ssid, str) or not ssid.strip():
            raise ValueError("Wi-Fi 名称不能为空")
        if not isinstance(password, str):
            raise ValueError("Wi-Fi 密钥必须是字符串")
        self.wifi_operations.put(("connect", {
            "ssid": ssid.strip(),
            "password": password,
        }))

    def has_pending_wifi_operation(self):
        """返回是否存在等待执行的 Wi-Fi 管理任务。"""
        return not self.wifi_operations.empty()

    def publish_wifi_operation(self):
        """执行一个 Wi-Fi 操作，并向托盘输出不含密钥的结构化结果。"""
        action, payload = self.wifi_operations.get_nowait()
        try:
            if action == "list":
                response = self.client.request_wifi_list()
            else:
                response = self.client.set_wifi(payload["ssid"], payload["password"])
            result = {
                "status": "ok",
                "action": action,
                "data": response.get("data") or {},
            }
        except (KeyError, OSError, RuntimeError, serial.SerialException) as error:
            result = {"status": "error", "action": action, "message": str(error)}
        print(
            "WIFI_RESULT:"
            + json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            flush=True,
        )
