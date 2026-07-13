"""定义设备端传输策略的公共接口。"""


class TransportStrategy:
    """定义 USB CDC 与 WebSocket 传输策略必须实现的接口。"""

    name = None

    def update(self):
        """推进连接状态、心跳和非阻塞网络收发。"""
        raise NotImplementedError

    def is_connected(self):
        """返回当前策略是否已经建立可用的双工连接。"""
        raise NotImplementedError

    def available(self):
        """返回当前可以立即读取的字节数。"""
        raise NotImplementedError

    def readinto(self, buffer):
        """把已收到的数据写入目标缓冲区并返回字节数。"""
        raise NotImplementedError

    def write(self, data):
        """发送字节数据并返回已接收的字节数。"""
        raise NotImplementedError

    def flush(self):
        """提交策略内部尚未发送的数据。"""
        return None

    def close(self):
        """关闭连接并释放策略持有的资源。"""
        return None

    def status(self):
        """返回供 PONG 上报的传输状态。"""
        return {"mode": self.name, "connected": self.is_connected()}
