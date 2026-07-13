"""把 WebSocket 双工连接适配为现有 PV1 读写框架可用的设备。"""

import threading
import time

import serial


class WebSocketDevice:
    """提供串口兼容接口的 WebSocket 客户端传输策略。"""

    def __init__(self, url, connect_timeout=5.0, read_timeout=0.3, heartbeat_interval=10.0):
        """连接指定 WebSocket 地址并初始化分帧与心跳状态。"""
        try:
            import websocket
        except ImportError as error:
            raise RuntimeError("WebSocket 模式需要安装 websocket-client") from error
        self._websocket_module = websocket
        self.port = str(url)
        self._socket = websocket.create_connection(
            self.port,
            timeout=max(0.1, float(connect_timeout)),
            enable_multithread=True,
        )
        self._socket.settimeout(max(0.05, float(read_timeout)))
        self._heartbeat_interval = max(1.0, float(heartbeat_interval))
        self._next_heartbeat = time.monotonic() + self._heartbeat_interval
        self._read_buffer = bytearray()
        self._write_buffer = bytearray()
        self._send_lock = threading.Lock()
        self._closed = False

    @property
    def is_open(self):
        """返回 WebSocket 底层连接是否仍然可用。"""
        return not self._closed and bool(getattr(self._socket, "connected", False))

    def _raise_if_closed(self):
        """连接关闭时抛出与现有通信重连逻辑兼容的异常。"""
        if not self.is_open:
            raise serial.SerialException("WebSocket 连接已断开")

    def reset_input_buffer(self):
        """清空本地 WebSocket 接收缓冲。"""
        self._read_buffer.clear()

    def reset_output_buffer(self):
        """清空尚未组装成完整 PV1 行的发送缓冲。"""
        self._write_buffer.clear()

    def _heartbeat_if_due(self):
        """到达心跳周期时发送 WebSocket Ping 控制帧。"""
        now = time.monotonic()
        if now < self._next_heartbeat:
            return
        try:
            with self._send_lock:
                self._raise_if_closed()
                self._socket.ping("pv1")
        except self._websocket_module.WebSocketException as error:
            self.close()
            raise serial.SerialException("WebSocket 心跳发送失败：{}".format(error)) from error
        self._next_heartbeat = now + self._heartbeat_interval

    def readline(self):
        """接收 WebSocket 消息并按换行边界返回一条 PV1 帧。"""
        while self.is_open:
            newline = self._read_buffer.find(b"\n")
            if newline >= 0:
                line = bytes(self._read_buffer[:newline + 1])
                del self._read_buffer[:newline + 1]
                return line
            self._heartbeat_if_due()
            try:
                message = self._socket.recv()
            except self._websocket_module.WebSocketTimeoutException:
                return b""
            except self._websocket_module.WebSocketException as error:
                self.close()
                raise serial.SerialException("WebSocket 接收失败：{}".format(error)) from error
            if message in (None, b"", ""):
                self.close()
                raise serial.SerialException("WebSocket 对端已关闭连接")
            if isinstance(message, str):
                message = message.encode("utf-8")
            self._read_buffer.extend(message)
        raise serial.SerialException("WebSocket 连接已断开")

    def write(self, data):
        """缓存发送片段，并在出现换行时发送完整的 PV1 消息。"""
        self._raise_if_closed()
        data = bytes(data)
        self._write_buffer.extend(data)
        self._send_complete_lines()
        return len(data)

    def _send_complete_lines(self):
        """把发送缓冲内的完整 PV1 行逐条作为二进制消息发出。"""
        while True:
            newline = self._write_buffer.find(b"\n")
            if newline < 0:
                return
            packet = bytes(self._write_buffer[:newline + 1])
            del self._write_buffer[:newline + 1]
            self._send_binary(packet)

    def _send_binary(self, packet):
        """线程安全地发送一个 WebSocket 二进制消息。"""
        with self._send_lock:
            self._raise_if_closed()
            try:
                self._socket.send_binary(packet)
            except self._websocket_module.WebSocketException as error:
                self.close()
                raise serial.SerialException("WebSocket 发送失败：{}".format(error)) from error

    def flush(self):
        """发送尚未以换行结尾的剩余数据。"""
        self._raise_if_closed()
        self._send_complete_lines()
        if self._write_buffer:
            packet = bytes(self._write_buffer)
            self._write_buffer.clear()
            self._send_binary(packet)

    def close(self):
        """幂等关闭 WebSocket 连接并清空本地缓冲。"""
        if self._closed:
            return
        self._closed = True
        try:
            self._socket.close()
        except Exception:
            pass
