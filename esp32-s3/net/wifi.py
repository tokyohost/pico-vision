"""管理 ESP32-S3 等 MicroPython 设备的 Wi-Fi 连接和持久化配置。"""

import time

try:
    import ujson as json
except ImportError:
    import json


class WifiManager:
    """负责 Wi-Fi 扫描、配置保存、连接以及断线重连。"""

    def __init__(self, config_path="wifi_config.json", reconnect_interval_ms=5000):
        """初始化无线网卡，并加载上次成功保存的网络配置。"""
        self._config_path = config_path
        self._reconnect_interval_ms = int(reconnect_interval_ms)
        self._wlan = None
        self._ssid = None
        self._password = None
        self._last_error = None
        self._next_reconnect_ms = 0
        try:
            import network

            self._wlan = network.WLAN(network.STA_IF)
            self._wlan.active(True)
        except (ImportError, AttributeError, OSError) as error:
            self._last_error = "WIFI_UNAVAILABLE:{}".format(error)
        self._load()

    @staticmethod
    def _ticks_ms():
        """返回兼容 CPython 与 MicroPython 的毫秒时钟。"""
        ticks_ms = getattr(time, "ticks_ms", None)
        return ticks_ms() if ticks_ms else int(time.monotonic() * 1000)

    @staticmethod
    def _due(now, deadline):
        """判断兼容回绕时钟的截止时间是否已经到达。"""
        ticks_diff = getattr(time, "ticks_diff", None)
        return ticks_diff(now, deadline) >= 0 if ticks_diff else now >= deadline

    @staticmethod
    def _add_ticks(value, delta):
        """以兼容时钟回绕的方式计算未来毫秒时刻。"""
        ticks_add = getattr(time, "ticks_add", None)
        return ticks_add(value, int(delta)) if ticks_add else value + int(delta)

    def _load(self):
        """从持久化文件加载 Wi-Fi 名称和密码。"""
        try:
            with open(self._config_path, "r") as source:
                values = json.loads(source.read())
        except (OSError, ValueError, TypeError):
            return
        ssid = values.get("ssid") if isinstance(values, dict) else None
        password = values.get("password") if isinstance(values, dict) else None
        if isinstance(ssid, str) and ssid:
            self._ssid = ssid
            self._password = password if isinstance(password, str) else ""

    def _save(self):
        """把当前 Wi-Fi 凭据以无 BOM UTF-8 JSON 保存到设备。"""
        with open(self._config_path, "w") as target:
            target.write(json.dumps({"ssid": self._ssid, "password": self._password}))

    def update(self):
        """在 Wi-Fi 断开后按固定间隔尝试重新连接已保存网络。"""
        if self._wlan is None or self.is_connected() or not self._ssid:
            return
        now = self._ticks_ms()
        if not self._due(now, self._next_reconnect_ms):
            return
        self._next_reconnect_ms = self._add_ticks(now, self._reconnect_interval_ms)
        try:
            self._wlan.active(True)
            self._wlan.connect(self._ssid, self._password or "")
            self._last_error = None
        except OSError as error:
            self._last_error = "WIFI_CONNECT_ERROR:{}".format(error)

    def scan(self):
        """扫描附近 Wi-Fi，并返回去重后的结构化网络列表。"""
        if self._wlan is None:
            raise RuntimeError(self._last_error or "WIFI_UNAVAILABLE")
        networks = {}
        for item in self._wlan.scan():
            ssid_bytes, bssid, channel, rssi, security, hidden = item[:6]
            ssid = ssid_bytes.decode("utf-8", "replace") if isinstance(ssid_bytes, bytes) else str(ssid_bytes)
            if not ssid:
                continue
            candidate = {
                "ssid": ssid,
                "bssid": ":".join("{:02x}".format(value) for value in bssid),
                "channel": channel,
                "rssi": rssi,
                "security": security,
                "hidden": bool(hidden),
            }
            previous = networks.get(ssid)
            if previous is None or candidate["rssi"] > previous["rssi"]:
                networks[ssid] = candidate
        return sorted(networks.values(), key=lambda item: item["rssi"], reverse=True)

    def connect(self, ssid, password, timeout_ms=15000):
        """连接指定 Wi-Fi，等待成功或超时，并保存成功凭据。"""
        if self._wlan is None:
            raise RuntimeError(self._last_error or "WIFI_UNAVAILABLE")
        ssid = str(ssid or "").strip()
        if not ssid:
            raise ValueError("WIFI_SSID_REQUIRED")
        password = str(password or "")
        if ssid == self._ssid and not password and self._password is not None:
            # 已保存网络允许不重复输入密钥；新网络仍按界面输入值连接。
            password = self._password
        self._wlan.active(True)
        if self._wlan.isconnected():
            self._wlan.disconnect()
        self._wlan.connect(ssid, password)
        started = self._ticks_ms()
        sleep_ms = getattr(time, "sleep_ms", None)
        while not self._wlan.isconnected():
            status = self._wlan.status()
            if status < 0:
                self._last_error = "WIFI_CONNECT_FAILED:{}".format(status)
                raise RuntimeError(self._last_error)
            now = self._ticks_ms()
            if self._due(now, self._add_ticks(started, timeout_ms)):
                self._last_error = "WIFI_CONNECT_TIMEOUT"
                raise RuntimeError(self._last_error)
            sleep_ms(100) if sleep_ms else time.sleep(0.1)
        self._ssid = ssid
        self._password = password
        self._last_error = None
        self._save()
        return self.status()

    def is_connected(self):
        """返回无线网卡是否已取得网络连接。"""
        return bool(self._wlan is not None and self._wlan.isconnected())

    def status(self):
        """返回不包含密码的 Wi-Fi 连接详情。"""
        link_status = None
        if self._wlan is not None:
            try:
                link_status = self._wlan.status()
            except OSError:
                pass
        details = {
            "available": self._wlan is not None,
            "connected": self.is_connected(),
            "ssid": self._ssid,
            "error": self._last_error,
            "link_status": link_status,
        }
        if not details["connected"] and link_status is not None and link_status < 0:
            details["error"] = details["error"] or "WIFI_STATUS:{}".format(link_status)
        if self.is_connected():
            ip, subnet, gateway, dns = self._wlan.ifconfig()
            details.update({"ip": ip, "subnet": subnet, "gateway": gateway, "dns": dns})
            try:
                details["rssi"] = self._wlan.status("rssi")
            except (OSError, ValueError):
                pass
        return details
