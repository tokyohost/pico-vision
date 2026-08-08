"""监听 ESP32 主动发送的 UDP 设备公告。"""

import json
import logging
import socket
import time
from dataclasses import dataclass


DISCOVERY_MAGIC = "FN_VISION_DISCOVERY"
DISCOVERY_VERSION = 1
DEFAULT_DISCOVERY_GROUP = "239.255.77.77"
DEFAULT_DISCOVERY_PORT = 37856
LOGGER = logging.getLogger("pico-monitor.discovery")


@dataclass(frozen=True)
class UdpAnnouncementResult:
    """描述一个经过格式校验的 ESP32 UDP 公告。"""

    ip: str
    port: int
    path: str
    device_id: str = ""

    @property
    def url(self):
        """返回可交给现有 WebSocket 客户端连接的地址。"""
        return "ws://{}:{}{}".format(self.ip, self.port, self.path)


class UdpAnnouncementListener:
    """在限定时间内监听组播和广播公告，并生成去重候选地址。"""

    def __init__(
        self,
        port=DEFAULT_DISCOVERY_PORT,
        group=DEFAULT_DISCOVERY_GROUP,
        timeout=3.0,
    ):
        """保存公告端口、组播地址和最长监听时间。"""
        self.port = int(port)
        self.group = str(group)
        self.timeout = max(0.05, float(timeout))

    def listen(self):
        """收集监听窗口内的合法公告；套接字异常按未发现设备处理。"""
        results = {}
        deadline = time.monotonic() + self.timeout
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            connection.bind(("", self.port))
            try:
                membership = socket.inet_aton(self.group) + socket.inet_aton("0.0.0.0")
                connection.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            except OSError as error:
                # 部分 Windows/VPN 网卡不允许在 INADDR_ANY 上加入组播；广播仍可接收。
                LOGGER.debug("加入 UDP 发现组播失败，将仅监听广播：%s", error)
            while time.monotonic() < deadline:
                connection.settimeout(max(0.01, deadline - time.monotonic()))
                try:
                    payload, source = connection.recvfrom(2048)
                except socket.timeout:
                    break
                candidate = self._parse(payload, source[0])
                if candidate is not None:
                    if candidate.url not in results:
                        LOGGER.info(
                            "[Wi-Fi发现][UDP公告] 收到 ESP32 设备公告："
                            "来源=%s:%s，设备UUID=%s，WebSocket候选=%s",
                            source[0],
                            source[1],
                            candidate.device_id or "未知",
                            candidate.url,
                        )
                    else:
                        LOGGER.debug(
                            "[Wi-Fi发现][UDP公告] 收到重复设备公告：来源=%s:%s，候选=%s",
                            source[0],
                            source[1],
                            candidate.url,
                        )
                    results[candidate.url] = candidate
        except OSError as error:
            LOGGER.warning("监听 ESP32 UDP 公告失败：%s", error)
        finally:
            connection.close()
        return list(results.values())

    @staticmethod
    def _parse(payload, source_ip):
        """校验公告协议，并始终采用数据报来源 IP 防止伪造连接地址。"""
        try:
            information = json.loads(payload.decode("utf-8"))
            if (
                information.get("magic") != DISCOVERY_MAGIC
                or int(information.get("version", 0)) != DISCOVERY_VERSION
            ):
                return None
            port = int(information.get("websocket_port", 0))
            path = "/" + str(information.get("websocket_path") or "").lstrip("/")
            if not 1 <= port <= 65535 or path == "/":
                return None
            return UdpAnnouncementResult(
                ip=str(source_ip),
                port=port,
                path=path,
                device_id=str(information.get("device_id") or ""),
            )
        except (AttributeError, UnicodeDecodeError, ValueError, TypeError):
            return None
