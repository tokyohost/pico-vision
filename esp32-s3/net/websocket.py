"""实现适用于 MicroPython 的轻量 WebSocket 服务端传输策略。"""

import time

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import usocket as socket
except ImportError:
    import socket

from net.base import TransportStrategy


class WebSocketTransport(TransportStrategy):
    """通过 Wi-Fi WebSocket 服务端提供 PV1 双工字节传输。"""

    name = "wifi"
    _GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, wifi_manager, port=8765, path="/pv1", heartbeat_ms=10000, timeout_ms=30000):
        """保存网络参数并初始化非阻塞服务端状态。"""
        self._wifi = wifi_manager
        self._port = int(port)
        self._path = path
        self._heartbeat_ms = int(heartbeat_ms)
        self._timeout_ms = int(timeout_ms)
        self._server = None
        self._client = None
        self._peer = None
        self._http_buffer = bytearray()
        self._wire_buffer = bytearray()
        self._receive_buffer = bytearray()
        self._last_receive_ms = None
        self._last_ping_ms = None

    @staticmethod
    def _ticks_ms():
        """返回兼容 CPython 与 MicroPython 的毫秒时钟。"""
        ticks_ms = getattr(time, "ticks_ms", None)
        return ticks_ms() if ticks_ms else int(time.monotonic() * 1000)

    @staticmethod
    def _elapsed(now, started):
        """计算兼容回绕时钟的毫秒间隔。"""
        if started is None:
            return 0
        ticks_diff = getattr(time, "ticks_diff", None)
        return ticks_diff(now, started) if ticks_diff else now - started

    def _open_server(self):
        """在 Wi-Fi 可用后创建非阻塞 WebSocket 监听套接字。"""
        if self._server is not None or not self._wifi.is_connected():
            return
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass
        server.bind(("0.0.0.0", self._port))
        server.listen(1)
        server.setblocking(False)
        self._server = server

    def _close_client(self):
        """关闭当前 WebSocket 客户端并清理全部会话缓冲。"""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
        self._peer = None
        self._http_buffer = bytearray()
        self._wire_buffer = bytearray()
        self._receive_buffer = bytearray()
        self._last_receive_ms = None
        self._last_ping_ms = None

    def _close_server(self):
        """关闭监听套接字和当前 WebSocket 会话。"""
        self._close_client()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def _accept(self):
        """非阻塞接受一个客户端，已有连接时拒绝额外客户端。"""
        if self._server is None or self._client is not None:
            return
        try:
            client, peer = self._server.accept()
        except OSError:
            return
        client.setblocking(False)
        self._client = client
        self._peer = peer
        self._last_receive_ms = self._ticks_ms()

    def _read_socket(self):
        """读取套接字数据并完成 HTTP 升级或 WebSocket 帧解析。"""
        if self._client is None:
            return
        try:
            data = self._client.recv(2048)
        except OSError:
            return
        if not data:
            self._close_client()
            return
        self._last_receive_ms = self._ticks_ms()
        if self._http_buffer is not None:
            self._http_buffer.extend(data)
            if b"\r\n\r\n" in self._http_buffer:
                self._upgrade(bytes(self._http_buffer))
            return
        self._wire_buffer.extend(data)
        self._parse_frames()

    def _upgrade(self, request):
        """校验 WebSocket HTTP 请求并返回协议升级响应。"""
        lines = request.split(b"\r\n")
        request_line = lines[0].split(b" ") if lines else ()
        if len(request_line) < 2 or request_line[1].decode("utf-8", "replace") != self._path:
            self._close_client()
            return
        headers = {}
        for line in lines[1:]:
            if b":" in line:
                key, value = line.split(b":", 1)
                headers[key.strip().lower()] = value.strip()
        key = headers.get(b"sec-websocket-key")
        if not key:
            self._close_client()
            return
        digest = hashlib.sha1(key + self._GUID).digest()
        accept = binascii.b2a_base64(digest).strip()
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        try:
            self._client.send(response)
        except OSError:
            self._close_client()
            return
        self._http_buffer = None
        self._wire_buffer = bytearray()
        now = self._ticks_ms()
        self._last_receive_ms = now
        self._last_ping_ms = now

    def _parse_frames(self):
        """增量解析客户端发送的掩码 WebSocket 帧。"""
        while len(self._wire_buffer) >= 2:
            first, second = self._wire_buffer[0], self._wire_buffer[1]
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            offset = 2
            if length == 126:
                if len(self._wire_buffer) < 4:
                    return
                length = (self._wire_buffer[2] << 8) | self._wire_buffer[3]
                offset = 4
            elif length == 127:
                self._close_client()
                return
            mask_size = 4 if masked else 0
            if len(self._wire_buffer) < offset + mask_size + length:
                return
            mask = self._wire_buffer[offset:offset + mask_size]
            payload_start = offset + mask_size
            payload = bytearray(self._wire_buffer[payload_start:payload_start + length])
            # MicroPython 的 bytearray 项删除支持不一致，
            # 通过重建剩余缓冲区消费完整帧，避免握手首帧触发 TypeError。
            self._wire_buffer = bytearray(
                self._wire_buffer[payload_start + length:]
            )
            if masked:
                for index in range(length):
                    payload[index] ^= mask[index & 3]
            if opcode in (0x1, 0x2):
                self._receive_buffer.extend(payload)
            elif opcode == 0x8:
                self._close_client()
                return
            elif opcode == 0x9:
                self._send_frame(0xA, payload)
            elif opcode == 0xA:
                self._last_receive_ms = self._ticks_ms()

    def _send_frame(self, opcode, payload=b""):
        """向 Monitor 发送一个未掩码 WebSocket 帧。"""
        if not self.is_connected():
            return False
        payload = bytes(payload)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 126, length >> 8, length & 0xFF))
        else:
            raise ValueError("WEBSOCKET_PAYLOAD_TOO_LARGE")
        packet = header + payload
        offset = 0
        try:
            while offset < len(packet):
                written = self._client.send(packet[offset:])
                if not written:
                    self._close_client()
                    return False
                offset += written
        except OSError:
            self._close_client()
            return False
        return True

    def update(self):
        """推进 Wi-Fi 重连、WebSocket 接入、数据接收和心跳检测。"""
        self._wifi.update()
        if not self._wifi.is_connected():
            self._close_server()
            return
        try:
            self._open_server()
        except OSError:
            self._close_server()
            return
        self._accept()
        self._read_socket()
        if not self.is_connected():
            return
        now = self._ticks_ms()
        if self._elapsed(now, self._last_receive_ms) >= self._timeout_ms:
            self._close_client()
            return
        if self._elapsed(now, self._last_ping_ms) >= self._heartbeat_ms:
            if self._send_frame(0x9, b"pv1"):
                self._last_ping_ms = now

    def is_connected(self):
        """返回 WebSocket 是否完成 HTTP 协议升级。"""
        return self._client is not None and self._http_buffer is None

    def available(self):
        """返回已解帧且可交给 PV1 协议层的字节数。"""
        return len(self._receive_buffer)

    def readinto(self, buffer):
        """从 WebSocket 接收缓冲复制数据到目标缓冲区。"""
        count = min(len(buffer), len(self._receive_buffer))
        if count <= 0:
            return 0
        buffer[:count] = self._receive_buffer[:count]
        # 与解帧缓冲保持相同的 MicroPython 兼容消费方式。
        self._receive_buffer = bytearray(self._receive_buffer[count:])
        return count

    def write(self, data):
        """把一段 PV1 数据作为二进制 WebSocket 消息发送。"""
        data = bytes(data)
        return len(data) if self._send_frame(0x2, data) else 0

    def close(self):
        """关闭 WebSocket 监听器和客户端。"""
        self._close_server()

    def status(self):
        """返回 Wi-Fi、WebSocket 服务及对端连接详情。"""
        details = self._wifi.status()
        details.update({
            "mode": self.name,
            "connected": self.is_connected(),
            "websocket_port": self._port,
            "websocket_path": self._path,
            "peer": self._peer[0] if self._peer else None,
        })
        return details
