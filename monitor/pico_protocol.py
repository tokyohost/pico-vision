#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""提供 Pico PV1 协议的帧编解码和 JSONZ 数据包构建能力。"""

import base64
import json
import zlib
from array import array


FRAME_MAGIC = b"PV1"
FRAME_MAX_PAYLOAD = 16 * 1024
TRANSPORT_BLOCK_SIZE = 64
ZLIB_WINDOW_BITS = 9


class PicoRestartingError(RuntimeError):
    """表示 Pico 报告不可恢复错误并正在自动重启。"""


class JsonAckTimeoutError(RuntimeError):
    """表示快照已经发送完成，但未在期限内收到对应 JSON ACK。"""


def _build_crc16_byte_table():
    """生成 CRC-16/CCITT 的字节查找表。"""
    table = []
    for value in range(256):
        crc = value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return array("H", table)


CRC16_BYTE_TABLE = _build_crc16_byte_table()


def crc16_ccitt(data):
    """使用字节查表计算 CRC-16/CCITT-FALSE。"""
    crc = 0xFFFF
    for value in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC16_BYTE_TABLE[((crc >> 8) ^ value) & 0xFF]
    return crc


def build_frame(message_type, payload=b""):
    """构建 PV1:type:length:crc:payload 帧。"""
    kind = message_type.encode("ascii") if isinstance(message_type, str) else bytes(message_type)
    payload = bytes(payload)
    checksum = crc16_ccitt(kind + b":" + payload)
    line = b":".join((
        FRAME_MAGIC,
        kind,
        str(len(payload)).encode("ascii"),
        f"{checksum:04X}".encode("ascii"),
        payload,
    ))
    padding = -(len(line) + 1) % TRANSPORT_BLOCK_SIZE
    return line + b" " * padding + b"\n"


def parse_frame(line):
    """校验并解析一条 PV1 帧；非 PV1 行返回 None。"""
    line = bytes(line).rstrip(b"\r\n")
    if not line.startswith(FRAME_MAGIC + b":"):
        return None
    parts = line.split(b":", 4)
    if len(parts) != 5:
        raise ValueError("BAD_FRAME_HEADER")
    _, kind, length_text, checksum_text, remainder = parts
    try:
        length = int(length_text)
        expected_crc = int(checksum_text, 16)
    except ValueError as error:
        raise ValueError("BAD_FRAME_HEADER") from error
    if length < 0 or length > FRAME_MAX_PAYLOAD or len(remainder) < length:
        raise ValueError("BAD_FRAME_LENGTH")
    payload, trailer = remainder[:length], remainder[length:]
    if trailer.strip(b" "):
        raise ValueError("BAD_FRAME_TRAILER")
    if crc16_ccitt(kind + b":" + payload) != expected_crc:
        raise ValueError("BAD_FRAME_CRC")
    return kind.decode("ascii"), payload


def build_jsonz_packet(payload):
    """压缩 JSON 字节并构建统一的 JSONZ 帧。"""
    # 使用 512 字节 zlib 窗口，避免 RP2040 解压时申请默认的 32KB 连续堆。
    compressor = zlib.compressobj(level=6, wbits=ZLIB_WINDOW_BITS)
    compressed = compressor.compress(payload) + compressor.flush()
    return build_frame("JSONZ", base64.b64encode(compressed))


def build_command_packet(command, params=None, request_id=None):
    """把命令策略名称和参数编码为 JSONZ 命令信封。"""
    message = {
        "mode": "command",
        "command": command,
        "params": params or {},
    }
    if request_id is not None:
        message["request_id"] = request_id
    payload = json.dumps(
        message,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return build_jsonz_packet(payload)


PING_COMMAND = build_frame("PING")
RESTARTING_FATAL_PREFIXES = (
    b"FATAL:MemoryError:",
    "FATAL:ValueError:脏矩形超过画布容量".encode("utf-8"),
)


def is_restarting_fatal(frame):
    """判断协议帧是否表示 Pico 正在因致命异常自动重启。"""
    return bool(
        frame
        and frame[0] == "EVENT"
        and any(frame[1].startswith(prefix) for prefix in RESTARTING_FATAL_PREFIXES)
    )
