"""生成不直接暴露芯片 MAC 的稳定设备 UUID。"""

try:
    import uhashlib as hashlib
except ImportError:
    import hashlib

try:
    import ubinascii as binascii
except ImportError:
    import binascii


_DEVICE_UUID = None


def _format_uuid(digest):
    """将 SHA-256 摘要前 128 位格式化为 RFC 兼容的 UUID v8。"""
    value = bytearray(digest[:16])
    # UUID v8 用于承载应用自定义哈希标识，变体位遵循 RFC 9562。
    value[6] = (value[6] & 0x0F) | 0x80
    value[8] = (value[8] & 0x3F) | 0x80
    hexadecimal = binascii.hexlify(value).decode("ascii")
    return "{}-{}-{}-{}-{}".format(
        hexadecimal[0:8],
        hexadecimal[8:12],
        hexadecimal[12:16],
        hexadecimal[16:20],
        hexadecimal[20:32],
    )


def device_uuid():
    """读取 ESP32-S3 eFuse MAC，经 SHA-256 生成并缓存稳定设备 UUID。"""
    global _DEVICE_UUID
    if _DEVICE_UUID is None:
        import machine

        efuse_mac = bytes(machine.unique_id())
        if not efuse_mac:
            raise RuntimeError("ESP32-S3 eFuse MAC 不可用")
        _DEVICE_UUID = _format_uuid(hashlib.sha256(efuse_mac).digest())
    return _DEVICE_UUID
