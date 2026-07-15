"""提供可复用的局域网 IPv4 WebSocket 服务并发发现能力。"""

import base64
import hashlib
import ipaddress
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

WEBSOCKET_ACCEPT_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _load_psutil():
    """按需加载网卡枚举依赖，避免传输模块导入时产生额外耦合。"""
    import psutil

    return psutil


@dataclass(frozen=True)
class WebSocketProbeResult:
    """描述一次成功的 WebSocket 协议升级握手结果。"""

    ip: str
    port: int
    path: str
    elapsed_ms: float

    @property
    def url(self):
        """返回可直接用于客户端连接的 WebSocket 地址。"""
        return "ws://{}:{}{}".format(self.ip, self.port, self.path)


class LanWebSocketScanner:
    """枚举本机局域网地址，并发执行低影响 WebSocket 协议升级握手。"""

    def __init__(
        self,
        port=8765,
        path="/pv1",
        timeout=0.35,
        max_workers=128,
        minimum_prefix_length=24,
    ):
        """保存探测参数，并限制单次主动扫描覆盖的最小 IPv4 前缀。"""
        self.port = int(port)
        self.path = "/" + str(path or "").lstrip("/")
        self.timeout = max(0.05, float(timeout))
        self.max_workers = max(1, int(max_workers))
        self.minimum_prefix_length = min(30, max(0, int(minimum_prefix_length)))

    @staticmethod
    def local_networks(minimum_prefix_length=24):
        """返回活动 IPv4 网段；过大的网段仅探测本机所在子网以降低广播域压力。"""
        psutil = _load_psutil()
        networks = set()
        limited_prefix_length = min(30, max(0, int(minimum_prefix_length)))
        statistics = psutil.net_if_stats()
        for interface_name, addresses in psutil.net_if_addrs().items():
            interface_statistics = statistics.get(interface_name)
            if interface_statistics is not None and not interface_statistics.isup:
                continue
            for address in addresses:
                if address.family != socket.AF_INET or not address.netmask:
                    continue
                ip = ipaddress.ip_address(address.address)
                if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                    continue
                try:
                    network = ipaddress.ip_network(
                        "{}/{}".format(address.address, address.netmask),
                        strict=False,
                    )
                except ValueError:
                    continue
                if network.prefixlen < limited_prefix_length:
                    network = ipaddress.ip_network(
                        "{}/{}".format(address.address, limited_prefix_length),
                        strict=False,
                    )
                networks.add(network)
        return tuple(sorted(networks, key=lambda item: (int(item.network_address), item.prefixlen)))

    @classmethod
    def local_hosts(cls, minimum_prefix_length=24):
        """合并全部局域网网段，返回去重且排除本机地址的可探测 IP。"""
        psutil = _load_psutil()
        local_addresses = {
            address.address
            for addresses in psutil.net_if_addrs().values()
            for address in addresses
            if address.family == socket.AF_INET
        }
        hosts = {
            str(host)
            for network in cls.local_networks(minimum_prefix_length)
            for host in network.hosts()
            if str(host) not in local_addresses
        }
        return tuple(sorted(hosts, key=lambda value: int(ipaddress.ip_address(value))))

    def scan(self, hosts=None, progress_callback=None):
        """先筛选端口开放地址，再验证 WebSocket 协议并返回成功结果。"""
        source_hosts = (
            self.local_hosts(self.minimum_prefix_length)
            if hosts is None
            else hosts
        )
        candidates = tuple(dict.fromkeys(str(host) for host in source_hosts))
        if not candidates:
            return []
        worker_count = min(self.max_workers, len(candidates))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="局域网端口探测",
        ) as executor:
            open_hosts = [
                host
                for host in executor.map(self._port_is_open_safely, candidates)
                if host is not None
            ]
        if not open_hosts:
            if progress_callback is not None:
                progress_callback(len(candidates), [])
            return []
        websocket_worker_count = min(self.max_workers, len(open_hosts))
        with ThreadPoolExecutor(
            max_workers=websocket_worker_count,
            thread_name_prefix="局域网WebSocket探测",
        ) as executor:
            results = list(executor.map(self._probe_safely, open_hosts))
        successful = [result for result in results if result is not None]
        successful.sort(key=lambda result: int(ipaddress.ip_address(result.ip)))
        if progress_callback is not None:
            progress_callback(len(candidates), successful)
        return successful

    def port_is_open(self, ip):
        """仅建立并立即关闭 TCP 连接，判断目标端口是否开放。"""
        with socket.create_connection((str(ip), self.port), timeout=self.timeout):
            return True

    def _port_is_open_safely(self, ip):
        """低成本检查单个地址端口，关闭或超时时返回空值。"""
        try:
            return str(ip) if self.port_is_open(ip) else None
        except OSError:
            return None

    def port_is_open_safely(self, ip):
        """公开执行端口快速检查，并以布尔值表示端口是否开放。"""
        return self._port_is_open_safely(ip) is not None

    def probe(self, ip):
        """连接单个 IPv4 地址，并校验其 WebSocket HTTP 升级响应。"""
        started = time.monotonic()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "X-OmniWatch-Discovery: 1\r\n\r\n"
        ).format(self.path, ip, self.port, key).encode("ascii")
        with socket.create_connection((str(ip), self.port), timeout=self.timeout) as connection:
            connection.settimeout(self.timeout)
            connection.sendall(request)
            response = self._receive_headers(connection)
        self._validate_handshake(response, key)
        return WebSocketProbeResult(
            ip=str(ip),
            port=self.port,
            path=self.path,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )

    def _probe_safely(self, ip):
        """探测单个地址，并将网络错误归一化为未发现结果。"""
        try:
            return self.probe(ip)
        except (OSError, ValueError):
            return None

    def probe_safely(self, ip):
        """公开执行单地址快速探测，并以空结果表示地址当前不可用。"""
        return self._probe_safely(ip)

    @staticmethod
    def _receive_headers(connection):
        """读取大小受限的 HTTP 响应头，防止异常服务持续占用内存。"""
        response = bytearray()
        while b"\r\n\r\n" not in response and len(response) < 8192:
            chunk = connection.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
        return bytes(response)

    @staticmethod
    def _validate_handshake(response, key):
        """校验状态码和 Sec-WebSocket-Accept，确认协议握手完整成功。"""
        try:
            header_text = response.decode("iso-8859-1")
            lines = header_text.split("\r\n")
            status_parts = lines[0].split(None, 2)
        except (UnicodeDecodeError, IndexError) as error:
            raise ValueError("WebSocket 握手响应无效") from error
        if len(status_parts) < 2 or status_parts[1] != "101":
            raise ValueError("服务未接受 WebSocket 协议升级")
        headers = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        if headers.get("upgrade", "").lower() != "websocket":
            raise ValueError("响应未声明 WebSocket 协议升级")
        connection_tokens = {
            token.strip().lower()
            for token in headers.get("connection", "").split(",")
        }
        if "upgrade" not in connection_tokens:
            raise ValueError("响应未确认 HTTP 连接升级")
        expected = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_ACCEPT_MAGIC).encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise ValueError("WebSocket 握手签名不匹配")
