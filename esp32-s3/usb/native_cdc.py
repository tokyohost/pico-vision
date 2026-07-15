"""封装固件内置的第二路 TinyUSB CDC 数据接口。"""


class NativeCdcUnavailable(RuntimeError):
    """表示当前固件没有编译内置数据 CDC 模块。"""


class NativeCdcStream:
    """把固件 C 模块适配为现有 PV1 传输使用的双工流。"""

    def __init__(self, backend):
        """保存固件原生 CDC 后端并校验接口版本。"""
        version = getattr(backend, "api_version", None)
        if not callable(version) or version() < 1:
            raise NativeCdcUnavailable("ESP32_S3_NATIVE_CDC_API_INVALID")
        initializer = getattr(backend, "init", None)
        if not callable(initializer):
            raise NativeCdcUnavailable("ESP32_S3_NATIVE_CDC_INIT_UNAVAILABLE")
        initializer()
        self._backend = backend

    def any(self):
        """返回 C 环形缓冲区中当前可读取的字节数。"""
        return self._backend.any()

    def readinto(self, buffer):
        """从 C 环形缓冲区批量读取数据。"""
        return self._backend.readinto(buffer)

    def write(self, data):
        """通过 TinyUSB 原生数据 CDC 发送字节。"""
        return self._backend.write(data)

    def flush(self):
        """立即提交 TinyUSB 数据 CDC 的发送 FIFO。"""
        return self._backend.flush()

    def is_open(self):
        """返回主机是否已经打开原生数据 CDC 端口。"""
        return bool(self._backend.is_open())

    def close(self):
        """保持固件内置 CDC 存活，关闭上层会话时无需释放端点。"""
        return None


def create_native_cdc_stream():
    """加载固件内置数据 CDC 模块并创建双工流。"""
    try:
        import _usb_cdc_data
    except ImportError as error:
        raise NativeCdcUnavailable("ESP32_S3_NATIVE_CDC_UNAVAILABLE") from error
    return NativeCdcStream(_usb_cdc_data)
