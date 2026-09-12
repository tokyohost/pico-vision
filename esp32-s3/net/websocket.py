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

try:
    import fn_websocket as _native_websocket
except ImportError:
    _native_websocket = None

from net.base import TransportStrategy
from net.websocket_clients import WebSocketClientRegistry


class WebSocketTransport(TransportStrategy):
    """通过 Wi-Fi WebSocket 服务端提供 PV1 双工字节传输。"""

    name = "wifi"

    def supports_binary_frames(self):
        """WebSocket 二进制消息可无损承载 JSONB。"""
        return True
    _GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    _MAX_HTTP_HEADER_BYTES = 4096
    _HANDSHAKE_TIMEOUT_MS = 2000
    _SEND_RETRY_TIMEOUT_MS = 250
    _WOULD_BLOCK_ERRNOS = (11, 35, 10035)
    _NATIVE_API_VERSION = 1

    def __init__(self, wifi_manager, port=8765, path="/pv1", heartbeat_ms=10000, timeout_ms=30000,
                 client_registry=None):
        """保存网络参数并初始化非阻塞服务端状态。"""
        self._wifi = wifi_manager
        self._port = int(port)
        self._path = path
        self._heartbeat_ms = int(heartbeat_ms)
        self._timeout_ms = int(timeout_ms)
        self._server = None
        self._client = None
        self._peer = None
        self._client_identity = None
        self._pending_client = None
        self._pending_peer = None
        self._pending_http_buffer = bytearray()
        self._pending_accepted_ms = None
        self._client_registry = client_registry or WebSocketClientRegistry()
        self._disconnect_after_write = False
        self._http_buffer = bytearray()
        self._wire_buffer = bytearray()
        self._receive_buffer = bytearray()
        self._last_receive_ms = None
        self._last_ping_ms = None
        self._accepted_ms = None
        self._native_attached = False
        self._native_receive_activity = 0

    @classmethod
    def _native_supported(cls):
        """返回固件是否包含兼容的 WebSocket 原生数据面。"""
        if _native_websocket is None:
            return False
        try:
            return (
                _native_websocket.api_version() == cls._NATIVE_API_VERSION
                and callable(getattr(_native_websocket, "attach", None))
                and callable(getattr(_native_websocket, "detach", None))
                and callable(getattr(_native_websocket, "frames_available", None))
                and callable(getattr(_native_websocket, "receive_activity", None))
                and callable(getattr(_native_websocket, "read_frame", None))
                and callable(getattr(_native_websocket, "read_error", None))
                and callable(getattr(_native_websocket, "send", None))
            )
        except Exception:
            return False

    def _attach_native(self):
        """把已完成 Upgrade 的 socket 交给 C 任务独占接收。"""
        self._native_attached = False
        if not self._native_supported() or self._client is None:
            return False
        fileno = getattr(self._client, "fileno", None)
        if not callable(fileno):
            return False
        try:
            _native_websocket.attach(fileno())
            self._native_attached = True
            self._native_receive_activity = int(
                _native_websocket.receive_activity()
            )
        except Exception:
            try:
                _native_websocket.detach()
            except Exception:
                pass
            self._native_attached = False
        return self._native_attached

    def _refresh_native_receive_activity(self):
        """把 C 任务观察到的网络活动同步到 Python 会话超时状态。"""
        if not self._native_attached:
            return
        activity = int(_native_websocket.receive_activity())
        if activity != self._native_receive_activity:
            self._native_receive_activity = activity
            self._last_receive_ms = self._ticks_ms()

    def _detach_native(self):
        """停止 C 任务访问当前 socket，随后才允许 Python 关闭连接。"""
        if not self._native_attached:
            return
        self._native_attached = False
        try:
            _native_websocket.detach()
        except Exception:
            pass

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

    @classmethod
    def _is_would_block_error(cls, error):
        """判断套接字异常是否仅表示非阻塞发送缓冲暂时不可写。"""
        error_number = getattr(error, "errno", None)
        if error_number is None and getattr(error, "args", None):
            error_number = error.args[0]
        return error_number in cls._WOULD_BLOCK_ERRNOS

    @staticmethod
    def _sleep_ms(delay_ms):
        """短暂让出处理器，并兼容 MicroPython 与 CPython 测试环境。"""
        sleep_ms = getattr(time, "sleep_ms", None)
        if callable(sleep_ms):
            sleep_ms(delay_ms)
        else:
            time.sleep(delay_ms / 1000)

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
        server.listen(2)
        server.setblocking(False)
        self._server = server

    def _close_client(self):
        """关闭当前 WebSocket 客户端并清理全部会话缓冲。"""
        self._detach_native()
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except OSError:
                pass
        self._peer = None
        self._client_identity = None
        self._http_buffer = bytearray()
        self._wire_buffer = bytearray()
        self._receive_buffer = bytearray()
        self._last_receive_ms = None
        self._last_ping_ms = None
        self._accepted_ms = None
        self._disconnect_after_write = False

    def _close_server(self):
        """关闭监听套接字和当前 WebSocket 会话。"""
        self._close_client()
        self._clear_pending_client()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def _accept(self):
        """非阻塞接受一个候选客户端，交由握手阶段执行优先级仲裁。"""
        if self._server is None or self._pending_client is not None:
            return
        try:
            client, peer = self._server.accept()
        except OSError:
            return
        client.setblocking(False)
        if self._client is None:
            self._client = client
            self._peer = peer
            self._http_buffer = bytearray()
            self._accepted_ms = self._ticks_ms()
            self._last_receive_ms = self._accepted_ms
            return
        self._pending_client = client
        self._pending_peer = peer
        self._pending_http_buffer = bytearray()
        self._pending_accepted_ms = self._ticks_ms()

    @staticmethod
    def _peer_address(peer):
        """把套接字对端信息转换为适合记录和展示的地址文本。"""
        return str(peer[0]) if peer else ""

    @staticmethod
    def _parse_http_request(request):
        """解析 WebSocket HTTP 请求行和小写请求头。"""
        lines = request.split(b"\r\n")
        request_line = lines[0].split(b" ") if lines else ()
        headers = {}
        for line in lines[1:]:
            if b":" in line:
                key, value = line.split(b":", 1)
                headers[key.strip().lower()] = value.strip()
        return request_line, headers

    @staticmethod
    def _send_http_rejection(client, status, reason):
        """向未获准候选连接发送明确 HTTP 状态后关闭套接字。"""
        try:
            body = reason.encode("utf-8")
            client.send(
                "HTTP/1.1 {}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                "Content-Length: {}\r\nConnection: close\r\n\r\n".format(
                    status, len(body)
                ).encode("ascii") + body
            )
        except OSError:
            pass
        try:
            client.close()
        except OSError:
            pass

    def _read_pending_socket(self):
        """读取候选握手，并在身份和优先级校验后决定拒绝或抢占。"""
        if self._pending_client is None:
            return
        try:
            data = self._pending_client.recv(2048)
        except OSError:
            return
        if not data:
            self._clear_pending_client()
            return
        self._pending_http_buffer.extend(data)
        if len(self._pending_http_buffer) > self._MAX_HTTP_HEADER_BYTES:
            self._reject_pending("431 Request Header Fields Too Large", "请求头过大")
            return
        if b"\r\n\r\n" not in self._pending_http_buffer:
            return
        self._upgrade_candidate(
            self._pending_client,
            self._pending_peer,
            bytes(self._pending_http_buffer),
            pending=True,
        )

    def _clear_pending_client(self, close=True):
        """关闭并清理当前候选连接。"""
        client, self._pending_client = self._pending_client, None
        if close and client is not None:
            try:
                client.close()
            except OSError:
                pass
        self._pending_peer = None
        self._pending_http_buffer = bytearray()
        self._pending_accepted_ms = None

    def _reject_pending(self, status, reason):
        """拒绝候选连接并释放候选槽位。"""
        client = self._pending_client
        if client is not None:
            self._send_http_rejection(client, status, reason)
        self._clear_pending_client(close=False)

    def _flush_registry_safely(self):
        """尝试保存客户端清单，存储异常不得中断 WebSocket 主循环。"""
        try:
            self._client_registry.flush()
        except Exception:
            # 客户端记录属于管理辅助数据；Flash 临时不可写时保留内存状态，
            # 后续连接或管理命令仍可再次尝试落盘，不能让设备进入致命等待。
            pass

    def _record_connected_safely(self, client_id, peer_address):
        """记录成功连接；持久化失败时维持当前会话继续运行。"""
        try:
            self._client_registry.record_connected(client_id, peer_address)
        except Exception:
            pass

    def _expire_handshakes(self, now):
        """关闭长期未完成 HTTP 升级的主连接和候选连接。"""
        if (
            self._client is not None
            and self._http_buffer is not None
            and self._elapsed(now, self._accepted_ms) >= self._HANDSHAKE_TIMEOUT_MS
        ):
            self._send_http_rejection(self._client, "408 Request Timeout", "握手超时")
            self._close_client()
        if (
            self._pending_client is not None
            and self._elapsed(now, self._pending_accepted_ms) >= self._HANDSHAKE_TIMEOUT_MS
        ):
            self._reject_pending("408 Request Timeout", "握手超时")

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
            if len(self._http_buffer) > self._MAX_HTTP_HEADER_BYTES:
                self._send_http_rejection(
                    self._client,
                    "431 Request Header Fields Too Large",
                    "请求头过大",
                )
                self._close_client()
                return
            if b"\r\n\r\n" in self._http_buffer:
                self._upgrade(bytes(self._http_buffer))
            return
        self._wire_buffer.extend(data)
        self._parse_frames()

    def _upgrade(self, request):
        """校验 WebSocket HTTP 请求并返回协议升级响应。"""
        self._upgrade_candidate(self._client, self._peer, request, pending=False)

    def _upgrade_candidate(self, client, peer, request, pending):
        """完成候选协议升级，并根据客户端策略保证唯一活动连接。"""
        request_line, headers = self._parse_http_request(request)
        if len(request_line) < 2 or request_line[1].decode("utf-8", "replace") != self._path:
            if pending:
                self._reject_pending("404 Not Found", "WebSocket 路径无效")
            else:
                self._close_client()
            return
        key = headers.get(b"sec-websocket-key")
        if not key:
            if pending:
                self._reject_pending("400 Bad Request", "缺少 WebSocket 密钥")
            else:
                self._close_client()
            return
        if headers.get(b"x-omniwatch-discovery") == b"1":
            digest = hashlib.sha1(key + self._GUID).digest()
            accept = binascii.b2a_base64(digest).strip()
            response = (
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
            )
            try:
                client.send(response)
            except OSError:
                pass
            if pending:
                self._clear_pending_client()
            else:
                self._close_client()
            return
        peer_address = self._peer_address(peer)
        client_id = headers.get(b"x-omniwatch-client-id", b"").decode("utf-8", "replace").strip()
        client_name = headers.get(b"x-omniwatch-device-name", b"").decode("utf-8", "replace").strip()
        if not client_id:
            client_id = "legacy:" + peer_address
        if not client_name:
            client_name = peer_address or client_id
        try:
            identity = self._client_registry.observe(client_id, client_name, peer_address)
        except Exception:
            if pending:
                self._reject_pending("400 Bad Request", "客户端身份无效")
            else:
                self._send_http_rejection(client, "400 Bad Request", "客户端身份无效")
                self._close_client()
            return
        if not identity.get("enabled", True):
            self._flush_registry_safely()
            if pending:
                self._reject_pending("403 Forbidden", "客户端已被禁用")
            else:
                self._send_http_rejection(client, "403 Forbidden", "客户端已被禁用")
                self._close_client()
            return
        current_priority = (self._client_identity or {}).get("priority", -1001)
        if pending and identity.get("priority", 0) <= current_priority:
            self._flush_registry_safely()
            self._reject_pending("409 Conflict", "已有同级或更高优先级客户端连接")
            return
        digest = hashlib.sha1(key + self._GUID).digest()
        accept = binascii.b2a_base64(digest).strip()
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        try:
            client.send(response)
        except OSError:
            if pending:
                self._clear_pending_client()
            else:
                self._close_client()
            return
        if pending:
            self._detach_native()
            old_client, self._client = self._client, client
            try:
                old_client.close()
            except OSError:
                pass
            self._peer = peer
            self._pending_client = None
            self._pending_peer = None
            self._pending_http_buffer = bytearray()
            self._pending_accepted_ms = None
        self._http_buffer = None
        self._wire_buffer = bytearray()
        self._receive_buffer = bytearray()
        self._client_identity = identity
        self._record_connected_safely(identity["id"], peer_address)
        now = self._ticks_ms()
        self._last_receive_ms = now
        self._last_ping_ms = now
        self._accepted_ms = None
        self._attach_native()

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
        retry_started_ms = self._ticks_ms()
        try:
            while offset < len(packet):
                try:
                    written = self._client.send(packet[offset:])
                except OSError as error:
                    if (
                        not self._is_would_block_error(error)
                        or self._elapsed(
                            self._ticks_ms(), retry_started_ms
                        ) >= self._SEND_RETRY_TIMEOUT_MS
                    ):
                        raise
                    # 显示设置会集中产生多条状态消息；非阻塞发送缓冲暂满
                    # 只需短暂让出处理器，不能误判为 WebSocket 已断开。
                    self._sleep_ms(1)
                    continue
                if not written:
                    self._close_client()
                    return False
                offset += written
                retry_started_ms = self._ticks_ms()
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
            self._accept()
            # 原生数据面接管后 Python 不再读取活动 socket，避免同方向并发 recv。
            if not self._native_attached:
                self._read_socket()
            else:
                self._refresh_native_receive_activity()
            self._read_pending_socket()
            now = self._ticks_ms()
            self._expire_handshakes(now)
            if not self.is_connected():
                return
            if self._elapsed(now, self._last_receive_ms) >= self._timeout_ms:
                self._close_client()
                return
            if self._elapsed(now, self._last_ping_ms) >= self._heartbeat_ms:
                if self._native_attached:
                    try:
                        ping_sent = _native_websocket.send(b"pv1", 0x9) == 3
                    except Exception:
                        ping_sent = False
                else:
                    ping_sent = self._send_frame(0x9, b"pv1")
                if ping_sent:
                    self._last_ping_ms = now
                else:
                    self._close_client()
        except MemoryError:
            # 内存不足必须交给设备顶层硬复位，避免在碎片化堆上反复重建服务。
            raise
        except Exception:
            # 畸形握手、套接字状态竞争或存储异常只重置网络服务，
            # 不得穿透到设备顶层并停止屏幕、按键和 LED 主循环。
            self._close_server()

    def is_connected(self):
        """返回 WebSocket 是否完成 HTTP 协议升级。"""
        return self._client is not None and self._http_buffer is None

    def available(self):
        """返回已解帧且可交给 PV1 协议层的字节数。"""
        if self._native_attached:
            try:
                return int(_native_websocket.frames_available())
            except Exception:
                self._close_client()
                return 0
        return len(self._receive_buffer)

    def uses_complete_frame_queue(self):
        """返回是否由 C 任务直接提供完整 WebSocket 消息。"""
        return self._native_attached

    def read_frame(self):
        """从 C 层 WebSocket 完整消息队列取出一帧 PV1 数据。"""
        if not self._native_attached:
            return None
        try:
            return _native_websocket.read_frame()
        except Exception:
            self._close_client()
            return None

    def read_receive_error(self):
        """取出 C 层异步接收错误，供协议层结束当前在途请求。"""
        if not self._native_attached:
            return None
        try:
            return _native_websocket.read_error()
        except Exception:
            self._close_client()
            return b"WEBSOCKET_NATIVE_ERROR"

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
        if self._native_attached:
            try:
                written = int(_native_websocket.send(data, 0x2))
            except Exception:
                written = 0
            if written != len(data):
                self._close_client()
                return 0
        else:
            written = len(data) if self._send_frame(0x2, data) else 0
        if self._disconnect_after_write:
            self._disconnect_after_write = False
            self._close_client()
        return written

    def close(self):
        """关闭 WebSocket 监听器和客户端。"""
        self._close_server()

    def status(self):
        """返回 Wi-Fi、WebSocket 服务及对端连接详情。"""
        details = self._wifi.status()
        details.update({
            "mode": self.name,
            "connected": self.is_connected(),
            "websocket_backend": "native" if self._native_attached else "python",
            "websocket_port": self._port,
            "websocket_path": self._path,
            "peer": self._peer[0] if self._peer else None,
            "client": dict(self._client_identity) if self._client_identity else None,
        })
        return details

    def list_clients(self):
        """返回曾连接客户端列表并标记当前活动客户端。"""
        active_id = (self._client_identity or {}).get("id")
        return self._client_registry.list_clients(active_id)

    def update_client(self, client_id, enabled=None, priority=None):
        """更新客户端策略；禁用当前客户端时在响应发送后断开。"""
        record = self._client_registry.update(client_id, enabled, priority)
        if (self._client_identity or {}).get("id") == client_id:
            self._client_identity = dict(record)
            if not record.get("enabled", True):
                self._disconnect_after_write = True
        return record
