"""选择 UF2 原生 PV1 解析器，并为旧固件保留 Python 回退能力。"""

try:
    import fn_protocol as _native_protocol
except ImportError:
    _native_protocol = None


NATIVE_PROTOCOL_API_VERSION = 1


def native_protocol_supported():
    """检查当前 UF2 是否完整提供兼容版本的原生协议接口。"""
    if _native_protocol is None:
        return False
    try:
        return (
            _native_protocol.api_version() == NATIVE_PROTOCOL_API_VERSION
            and callable(getattr(_native_protocol, "parse_frame", None))
        )
    except (AttributeError, TypeError, ValueError):
        return False


def parse_frame_native(line, maximum_payload_size):
    """调用固件原生模块校验 PV1 帧并返回消息类型和载荷。"""
    return _native_protocol.parse_frame(line, maximum_payload_size)
