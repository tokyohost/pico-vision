#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.
#
#  Any project, software, or derivative work that uses, modifies, links to,
#  or incorporates this software must make its complete source code publicly
#  available under the same license.
#
#  This software is provided "as is", without warranty of any kind.



"""实现可承载于 USB 或 WebSocket 的 PV1 握手与 JSON 接收协议。"""


import sys
import time
import gc
import os
from array import array

try:
    import uselect as select
except ImportError:
    import select

try:
    import ujson as json
except ImportError:
    import json

try:
    import zlib

    ZLIB_ERROR = getattr(zlib, "error", ValueError)


    def decompress_zlib(data):
        """使用固件 zlib 模块解压缩数据。"""
        return zlib.decompress(data, 15)
except ImportError:
    import deflate

    try:
        import io
    except ImportError:
        import uio as io

    ZLIB_ERROR = OSError


    def decompress_zlib(data):
        """使用 MicroPython deflate 流解压缩数据。"""
        source = io.BytesIO(data)
        stream = deflate.DeflateIO(source, deflate.ZLIB, 9)
        try:
            return stream.read()
        finally:
            stream.close()

try:
    import ubinascii as binascii
except ImportError:
    import binascii

from config import (
    BOARD_MODEL,
    DEVICE_NAME,
    FIRMWARE_VERSION,
    LCD_DEVICE_TYPE,
    LCD_DRIVER,
    MAX_JSON_SIZE,
    MAX_UPGRADE_LINE_SIZE,
    PIXEL_FORMAT,
    SERIAL_READ_BUDGET,
)
import protocolC
from device_identity import device_uuid


def runtime_sdk_version():
    """返回当前 MicroPython SDK 的定制版本号并移除构建日期。"""
    try:
        uname = os.uname()
        version = getattr(uname, "version", None)
        if version is None and len(uname) > 3:
            version = uname[3]
    except (AttributeError, OSError, TypeError):
        version = None
    normalized = str(version or "").strip()
    if " on " in normalized:
        normalized = normalized.split(" on ", 1)[0].strip()
    return normalized or "未知"


def sdk_update_supported():
    """返回当前 ESP32-S3 SDK 是否提供软件进入 ROM 下载模式的能力。"""
    try:
        import machine

        return callable(getattr(machine, "bootloader", None))
    except ImportError:
        return False


def _build_crc16_byte_table():
    """生成仅占约 512 字节的 CRC-16/CCITT 字节查找表。"""
    table = []
    for value in range(256):
        crc = value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return array("H", table)


CRC16_BYTE_TABLE = _build_crc16_byte_table()
TRANSPORT_BLOCK_SIZE = 64
JSONB_CHUNK_HEADER_SIZE = 13
JSONB_CHUNK_VERSION = 1
JSONZ_GC_FREE_THRESHOLD = 72 * 1024
# 限制未提交事务的序列化体积，防止网络缺片期间无限累积。
SNAPSHOT_TRANSACTION_MAX_BYTES = 262144


def _collect_jsonz_garbage_if_needed():
    """仅在 JSONZ 可用堆低于安全线时回收临时对象。"""
    try:
        if gc.mem_free() >= JSONZ_GC_FREE_THRESHOLD:
            return False
    except AttributeError:
        pass
    gc.collect()
    return True


def _json_error_payload(stage, error=None, detail=None):
    """生成简短 ASCII JSON 错误，方便主机端定位 BAD_JSON 的真实阶段。"""
    try:
        if error is not None:
            name = error.__class__.__name__
            message = str(error)
        else:
            name = "Error"
            message = str(detail or "")
    except Exception:
        name = "Error"
        message = ""

    try:
        import gc

        memory = ":MEM_FREE={}:MEM_ALLOC={}".format(
            gc.mem_free(),
            gc.mem_alloc(),
        )
    except Exception:
        memory = ""

    text = "BAD_JSON:{}:{}:{}{}".format(
        stage,
        name,
        message,
        memory,
    )
    text = text.replace("\r", " ").replace("\n", " ")
    return text[:220].encode("ascii", "replace")


class JsonProtocol:
    """增量接收 PV1 文本帧与 JSONB 二进制分片。"""

    def __init__(self, upgrade_manager=None, stream=None):
        """初始化标准输入输出、轮询器和行缓冲区。"""
        self._dedicated_stream = stream is not None
        self._input = stream if stream is not None else sys.stdin
        self._reader = stream if stream is not None else getattr(sys.stdin, "buffer", sys.stdin)
        self._output = stream if stream is not None else getattr(sys.stdout, "buffer", sys.stdout)
        self._poller = None if callable(getattr(stream, "available", None)) else select.poll()
        # ESP32-S3 内置 USB 控制台由传输层提供可轮询对象，协议层只负责读取。
        if self._poller is not None:
            self._poller.register(self._input, select.POLLIN)
        self._buffer = bytearray()
        # 一次尽量排空本轮读取预算，避免 micropython-lib Buffer 在部分读取后
        # 多次搬移剩余数据，也让 CDC OUT 端点更早恢复可接收状态。
        self._read_buffer = bytearray(
            SERIAL_READ_BUDGET if self._dedicated_stream else 1
        )
        self._last_byte_ms = None
        self._frame_started_ms = None
        self._frame_read_calls = 0
        self._upgrade_manager = upgrade_manager
        self._command_registry = None
        self._command_services = {"upgrade_manager": self._upgrade_manager}
        self._last_message_ms = None
        # 快照事务只在全部分片收齐后提交，避免设备显示半份数组。
        self._snapshot_chunk_transaction = None
        self._jsonb_transfer = None
        self._committed_snapshot = None
        self._committed_batch = None

    def set_command_services(self, services):
        """合并应用层命令服务，供延迟创建的命令策略注册表使用。"""
        if services:
            self._command_services.update(services)

    @staticmethod
    def protocol_backend():
        """返回当前 PV1 帧解析所使用的协议后端名称。"""
        return "C" if protocolC.native_protocol_supported() else "PYTHON"

    def _write_raw(self, data):
        """向 USB 串口写入 PV1 帧，主机断开时放弃发送以免阻塞主循环。"""
        data = bytes(data)
        offset = 0
        stalled_since_ms = None
        preferred_write_size = getattr(self._output, "preferred_write_size", None)
        write_size = preferred_write_size() if callable(preferred_write_size) else 63
        while offset < len(data):
            # 避免写满 64 字节 USB 端点后立即继续写入导致 CDC 暂时返回零。
            remaining = data[offset:offset + write_size]
            try:
                written = self._output.write(remaining)
            except TypeError:
                self._output.write(remaining.decode("utf-8"))
                written = len(remaining)
            except OSError:
                # 独立 CDC 在主机进程被强制结束时可能直接报告写入失败。
                # 诊断帧允许丢弃，不能让通信异常终止固件主循环。
                if self._dedicated_stream:
                    return False
                raise
            # 部分流实现成功写入全部数据后返回 None，按完整写入处理。
            if written is None:
                written = len(remaining)
            if written < 0:
                if self._dedicated_stream:
                    return False
                raise OSError("SERIAL_WRITE_FAILED")
            if written == 0:
                # CDC 断开和发送缓冲区已满都会返回零。主机已关闭端口时立即
                # 放弃；端口仍打开时最多等待 100 毫秒，避免永久卡死。
                is_open = getattr(self._output, "is_open", None)
                if self._dedicated_stream and callable(is_open) and not is_open():
                    return False
                now = self._ticks_ms()
                if stalled_since_ms is None:
                    stalled_since_ms = now
                elif self._elapsed_ms(now, stalled_since_ms) >= 100:
                    return False
                try:
                    self._output.flush()
                except Exception:
                    pass
                sleep_ms = getattr(time, "sleep_ms", None)
                sleep_ms(2) if sleep_ms else time.sleep(0.002)
                continue
            stalled_since_ms = None
            offset += written
            try:
                self._output.flush()
            except Exception:
                pass
            if offset < len(data):
                sleep_ms = getattr(time, "sleep_ms", None)
                sleep_ms(2) if sleep_ms else time.sleep(0.002)
        return True

    def write(self, data):
        """把应用诊断消息封装为 PV1 EVENT 帧。"""
        self._write_frame("EVENT", bytes(data).strip())

    def poll(self):
        """在固定读取预算内接收数据并返回最新完整 JSON 对象。"""
        self._expire_partial_frame()
        complete_frame_queue = getattr(self._reader, "uses_complete_frame_queue", None)
        if callable(complete_frame_queue) and complete_frame_queue():
            return self._poll_complete_frames()
        read_count = 0
        while read_count < SERIAL_READ_BUDGET and self._input_available():
            received = self._reader.readinto(self._read_buffer)
            if not received:
                break
            self._buffer.extend(memoryview(self._read_buffer)[:received])
            self._last_byte_ms = self._ticks_ms()
            read_count += received
            self._frame_read_calls += 1
            self._synchronize_magic()
            maximum_size = max(MAX_JSON_SIZE + 64, MAX_UPGRADE_LINE_SIZE + 64)
            if len(self._buffer) > maximum_size:
                self._buffer = bytearray()
                self._last_byte_ms = None
                self._frame_started_ms = None
                self._frame_read_calls = 0
                self._write_frame("ERR", b"FRAME_TOO_LARGE")
                return None
        return self._parse_lines()

    def _poll_complete_frames(self):
        """仅取出 C 任务已组装的完整帧，Python 不再持有 USB 半包。"""
        read_count = 0
        reader = getattr(self._reader, "read_frame", None)
        error_reader = getattr(self._reader, "read_receive_error", None)
        while read_count < SERIAL_READ_BUDGET and self._input_available():
            receive_error = error_reader() if callable(error_reader) else None
            if receive_error:
                self._buffer = bytearray()
                self._last_byte_ms = None
                self._frame_started_ms = None
                self._frame_read_calls = 0
                self._write_frame("ERR", bytes(receive_error))
                continue
            frame = reader() if callable(reader) else None
            if not frame:
                break
            self._buffer.extend(frame)
            read_count += len(frame)
            self._last_byte_ms = self._ticks_ms()
            self._frame_read_calls += 1
        return self._parse_lines()

    def is_busy(self):
        """判断串口是否有待接收字节或未完成的行。"""
        return bool(self._buffer) or self._input_available()

    def _input_available(self):
        """兼容策略流和系统流，判断是否存在可立即读取的数据。"""
        available = getattr(self._input, "available", None)
        if callable(available):
            return bool(available())
        return bool(self._poller.poll(0))

    def _next_frame_end(self):
        """按 PV1 头部长度返回完整帧末端，允许 JSONB 载荷包含换行字节。"""
        if not self._buffer.startswith(b"PV1:"):
            newline = self._buffer.find(b"\n")
            return newline + 1 if newline >= 0 else None
        separators = []
        search_start = 0
        for _ in range(4):
            separator = self._buffer.find(b":", search_start)
            if separator < 0:
                newline = self._buffer.find(b"\n")
                return newline + 1 if newline >= 0 else None
            separators.append(separator)
            search_start = separator + 1
        message_type = bytes(self._buffer[separators[0] + 1:separators[1]])
        try:
            payload_size = int(bytes(self._buffer[separators[1] + 1:separators[2]]))
        except (TypeError, ValueError):
            newline = self._buffer.find(b"\n")
            return newline + 1 if newline >= 0 else None
        payload_end = separators[3] + 1 + max(0, payload_size)
        # JSONZ 等文本帧继续兼容无填充行；JSONB 的换行属于合法载荷，
        # 必须严格根据长度和 64 字节物理边界定位帧尾。
        if message_type != b"JSONB":
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                return newline + 1
        frame_end = ((payload_end + TRANSPORT_BLOCK_SIZE) // TRANSPORT_BLOCK_SIZE) * TRANSPORT_BLOCK_SIZE
        if len(self._buffer) < frame_end:
            return None
        if self._buffer[frame_end - 1] != 0x0A:
            newline = self._buffer.find(b"\n", payload_end)
            return newline + 1 if newline >= 0 else None
        return frame_end

    def _parse_lines(self):
        """依次解析完整 PV1 帧，并合并同一次轮询收到的全部 JSON 快照。"""
        latest = None
        while True:
            frame_end = self._next_frame_end()
            if frame_end is None:
                break

            # memoryview 避免 bytearray 切片先复制一次整包数据，降低解析峰值内存。
            line_view = memoryview(self._buffer)[:frame_end - 1]
            line = bytes(line_view)
            del line_view

            receive_finished_ms = self._ticks_ms()
            receive_elapsed_ms = self._elapsed_ms(
                receive_finished_ms,
                self._frame_started_ms,
            )
            frame_read_calls = self._frame_read_calls
            self._consume(frame_end)

            # 串口可能先被 ModemManager 等程序写入无换行的探测字节；扫描魔数，
            # 从同一行中的首个 PV1 帧重新同步，而不是连合法帧一起丢弃。
            frame_start = line.find(b"PV1:")
            if frame_start < 0:
                continue

            line = line[frame_start:]

            try:
                parse_started_ms = self._ticks_ms()
                message_type, payload = self._parse_frame(line)
                self._last_message_ms = receive_finished_ms
                parse_elapsed_ms = self._elapsed_ms(
                    self._ticks_ms(),
                    parse_started_ms,
                )
            except ValueError as error:
                self._write_frame(
                    "ERR",
                    self._frame_error_payload(
                        error,
                        line,
                        frame_read_calls=frame_read_calls,
                    ),
                )
                continue

            if message_type == "PING":
                # 新连接从完整快照重新建立基线，丢弃断线前未完成的事务。
                self._snapshot_chunk_transaction = None
                self._jsonb_transfer = None
                self._committed_batch = None
                self._write_pong()
            elif message_type == "JSONZ":
                snapshot = self._handle_jsonz_frame(
                    payload=payload,
                    line=line,
                    frame_read_calls=frame_read_calls,
                    receive_elapsed_ms=receive_elapsed_ms,
                    parse_elapsed_ms=parse_elapsed_ms,
                )
                if snapshot is not None:
                    # 事务返回的是完整状态，不能递归并回已删除的旧字段。
                    latest = snapshot if snapshot is self._committed_snapshot else self._merge_parsed_snapshots(latest, snapshot)
            elif message_type == "JSONB":
                snapshot = self._handle_jsonb_frame(
                    payload=payload,
                    line=line,
                    frame_read_calls=frame_read_calls,
                    receive_elapsed_ms=receive_elapsed_ms,
                    parse_elapsed_ms=parse_elapsed_ms,
                )
                if snapshot is not None:
                    latest = snapshot if snapshot is self._committed_snapshot else self._merge_parsed_snapshots(latest, snapshot)
            else:
                self._write_frame("ERR", b"UNKNOWN_TYPE")
        return latest

    @classmethod
    def _merge_parsed_snapshots(cls, previous, incoming):
        """递归合并同批 JSON 快照，确保较早分片不会被后续分片覆盖丢失。"""
        if not isinstance(previous, dict) or not isinstance(incoming, dict):
            return incoming
        merged = dict(previous)
        for key, value in incoming.items():
            old_value = merged.get(key)
            if isinstance(old_value, dict) and isinstance(value, dict):
                merged[key] = cls._merge_parsed_snapshots(old_value, value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _clone_snapshot_value(value):
        """递归复制 JSON 值，兼容未提供 copy.deepcopy 的 MicroPython。"""
        if isinstance(value, dict):
            return {key: JsonProtocol._clone_snapshot_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [JsonProtocol._clone_snapshot_value(item) for item in value]
        return value

    @classmethod
    def _snapshot_path_parent(cls, root, path, create=False):
        """定位操作路径的父容器，并按需创建字典或数组节点。"""
        current = root
        for index, part in enumerate(path[:-1]):
            next_part = path[index + 1]
            if isinstance(current, dict):
                if part not in current or not isinstance(current[part], (dict, list)):
                    if not create:
                        return None, None
                    current[part] = [] if isinstance(next_part, int) else {}
                current = current[part]
            elif isinstance(current, list) and isinstance(part, int):
                while len(current) <= part:
                    current.append(None)
                if not isinstance(current[part], (dict, list)):
                    if not create:
                        return None, None
                    current[part] = [] if isinstance(next_part, int) else {}
                current = current[part]
            else:
                return None, None
        return current, path[-1] if path else None

    @classmethod
    def _snapshot_set_path(cls, root, path, value):
        """设置 JSON 路径并返回可能被根路径替换后的对象。"""
        if not path:
            return cls._clone_snapshot_value(value)
        parent, key = cls._snapshot_path_parent(root, path, True)
        value = cls._clone_snapshot_value(value)
        if isinstance(parent, dict):
            parent[key] = value
        elif isinstance(parent, list) and isinstance(key, int):
            while len(parent) <= key:
                parent.append(None)
            parent[key] = value
        else:
            raise ValueError("SNAPSHOT_PATH_INVALID")
        return root

    @classmethod
    def _snapshot_get_path(cls, root, path):
        """读取 JSON 路径，缺失时返回空值。"""
        current = root
        for part in path:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and isinstance(part, int) and part < len(current):
                current = current[part]
            else:
                return None
        return current

    @classmethod
    def _apply_snapshot_chunk_ops(cls, base, operations):
        """将事务操作应用到暂存快照，支持数组偏移、扩容、移位和文本续传。"""
        # 全量首操作覆盖根时，不复制即将丢弃的大型旧快照。
        iterator = iter(operations)
        first = next(iterator, None)
        if first is None:
            return cls._clone_snapshot_value(base) if isinstance(base, dict) else {}
        full_reset = first.get("op") == "set" and first.get("path") == []
        root = {} if full_reset else cls._clone_snapshot_value(base) if isinstance(base, dict) else {}

        def pending_operations():
            """以迭代方式消费分片，避免额外建立全事务操作列表。"""
            yield first
            for item in iterator:
                yield item

        operations = pending_operations()
        for operation in operations:
            path = operation.get("path") or []
            if not isinstance(path, list):
                raise ValueError("SNAPSHOT_PATH_INVALID")
            op = operation.get("op")
            if op == "set":
                root = cls._snapshot_set_path(root, path, operation.get("value"))
            elif op == "delete":
                parent, key = cls._snapshot_path_parent(root, path)
                if isinstance(parent, dict):
                    parent.pop(key, None)
                elif isinstance(parent, list) and isinstance(key, int) and key < len(parent):
                    parent.pop(key)
            elif op in ("resize", "items", "shift"):
                values = cls._snapshot_get_path(root, path)
                if not isinstance(values, list):
                    values = []
                    root = cls._snapshot_set_path(root, path, values)
                if op == "resize":
                    length = max(0, int(operation.get("length", 0)))
                    if operation.get("reset"):
                        values[:] = [None] * length
                    else:
                        del values[length:]
                        while len(values) < length:
                            values.append(None)
                elif op == "items":
                    start = max(0, int(operation.get("start", 0)))
                    for offset, item in enumerate(operation.get("values") or []):
                        while len(values) <= start + offset:
                            values.append(None)
                        values[start + offset] = cls._clone_snapshot_value(item)
                else:
                    start = max(0, int(operation.get("start", 0)))
                    length = max(0, int(operation.get("length", len(values))))
                    shifted = values[start:]
                    del values[:]
                    values.extend(shifted[:length])
                    while len(values) < length:
                        values.append(None)
            elif op == "text":
                current = cls._snapshot_get_path(root, path)
                if not isinstance(current, str):
                    current = ""
                start = max(0, int(operation.get("start", 0)))
                text = str(operation.get("value") or "")
                total = max(start + len(text), int(operation.get("length", 0)))
                current = current[:start] + text + current[start + len(text):]
                current = current[:total]
                root = cls._snapshot_set_path(root, path, current)
            else:
                raise ValueError("SNAPSHOT_OP_INVALID")
        return root

    def _handle_snapshot_chunk(self, message, payload_size=None):
        """接收事务分片；收齐后一次应用并返回完整快照，否则返回空值。"""
        batch = str(message.get("batch") or "")
        base = message.get("base")
        try:
            sequence = int(message.get("seq"))
            count = int(message.get("count"))
        except (TypeError, ValueError):
            raise ValueError("SNAPSHOT_CHUNK_HEADER_INVALID")
        if not batch or sequence < 0 or count <= 0 or sequence >= count or count > 4096:
            raise ValueError("SNAPSHOT_CHUNK_HEADER_INVALID")
        operations = message.get("ops")
        if not isinstance(operations, list):
            raise ValueError("SNAPSHOT_CHUNK_OPS_INVALID")
        full_reset = any(
            isinstance(item, dict) and item.get("op") == "set" and item.get("path") == []
            for item in operations
        )
        transaction = self._snapshot_chunk_transaction
        now = self._ticks_ms()
        if transaction is not None and self._elapsed_ms(now, transaction.get("started")) >= 10000:
            transaction = None
            self._snapshot_chunk_transaction = None
        if transaction is None or transaction.get("batch") != batch:
            # 发送端在断线、ACK 超时或基线不确定时会从根路径重发完整快照。
            if base != self._committed_batch and not (base is None and full_reset):
                raise ValueError("SNAPSHOT_CHUNK_BASE_MISMATCH")
            transaction = {"batch": batch, "base": base, "count": count,
                           "parts": {}, "started": now, "bytes": 0}
            self._snapshot_chunk_transaction = transaction
        elif transaction.get("count") != count or transaction.get("base") != base:
            raise ValueError("SNAPSHOT_CHUNK_HEADER_MISMATCH")
        previous = transaction["parts"].get(sequence)
        if previous is None:
            size = payload_size if payload_size is not None else len(json.dumps(message).encode("utf-8"))
            total_bytes = transaction.get("bytes", 0) + size
            if total_bytes > SNAPSHOT_TRANSACTION_MAX_BYTES:
                self._snapshot_chunk_transaction = None
                raise ValueError("SNAPSHOT_CHUNK_BYTES_EXCEEDED")
            transaction["bytes"] = total_bytes
        if previous is not None:
            if previous != operations:
                raise ValueError("SNAPSHOT_CHUNK_DUPLICATE_MISMATCH")
        else:
            transaction["parts"][sequence] = operations
        if len(transaction["parts"]) != count:
            return None
        def ordered_operations():
            """按序消费已收齐的分片，提交期间不额外复制操作引用。"""
            for index in range(count):
                for operation in transaction["parts"][index]:
                    yield operation

        all_operations = ordered_operations()
        apply_started = self._ticks_ms()
        try:
            snapshot = self._apply_snapshot_chunk_ops(self._committed_snapshot, all_operations)
            if not isinstance(snapshot, dict):
                raise ValueError("SNAPSHOT_DATA_REQUIRED")
        finally:
            # 应用失败同样释放暂存操作，低内存设备不能继续保留整个失败批次。
            self._snapshot_chunk_transaction = None
        self._snapshot_commit_timing = "PARTS={}:BYTES={}:APPLY={}MS:TRANSACTION={}MS".format(
            count, transaction.get("bytes", 0),
            self._elapsed_ms(self._ticks_ms(), apply_started),
            self._elapsed_ms(self._ticks_ms(), transaction["started"]),
        )
        self._committed_snapshot = snapshot
        self._committed_batch = batch
        return snapshot

    def _handle_jsonz_frame(
            self,
            payload,
            line,
            frame_read_calls,
            receive_elapsed_ms,
            parse_elapsed_ms,
    ):
        """分阶段解析 JSONZ，并返回更具体的 BAD_JSON 错误。"""
        return self._handle_compressed_json_frame(
            payload, line, frame_read_calls, receive_elapsed_ms,
            parse_elapsed_ms, "JSONZ", True,
        )

    def _handle_jsonb_frame(
            self, payload, line, frame_read_calls,
            receive_elapsed_ms, parse_elapsed_ms,
    ):
        """按顺序拼接 JSONB 压缩字节，收齐后一次解压完整快照。"""
        if len(payload) < JSONB_CHUNK_HEADER_SIZE or payload[0] != JSONB_CHUNK_VERSION:
            self._jsonb_transfer = None
            self._write_frame("ERR", b"BAD_JSONB_HEADER")
            return None
        request_id = ((payload[1] << 24) | (payload[2] << 16) | (payload[3] << 8) | payload[4])
        sequence = (payload[5] << 8) | payload[6]
        count = (payload[7] << 8) | payload[8]
        total_size = ((payload[9] << 24) | (payload[10] << 16) | (payload[11] << 8) | payload[12])
        chunk = payload[JSONB_CHUNK_HEADER_SIZE:]
        if count < 1 or sequence >= count or total_size > SNAPSHOT_TRANSACTION_MAX_BYTES:
            self._jsonb_transfer = None
            self._write_frame("ERR", b"BAD_JSONB_LIMIT")
            return None

        transfer = getattr(self, "_jsonb_transfer", None)
        if sequence == 0:
            try:
                transfer = {
                    "request": request_id,
                    "count": count,
                    "total": total_size,
                    "next": 0,
                    "offset": 0,
                    # 预分配避免每片 extend 触发反复扩容、复制和堆碎片。
                    "data": bytearray(total_size),
                    "wire": 0,
                    "updated": self._ticks_ms(),
                }
            except MemoryError as error:
                self._jsonb_transfer = None
                self._write_frame("ERR", _json_error_payload("MEMORY_JSONB", error))
                return None
            self._jsonb_transfer = transfer
        if (
                transfer is None
                or transfer["request"] != request_id
                or transfer["count"] != count
                or transfer["total"] != total_size
                or transfer["next"] != sequence
        ):
            self._jsonb_transfer = None
            self._write_frame("ERR", b"BAD_JSONB_SEQUENCE")
            return None
        chunk_end = transfer["offset"] + len(chunk)
        if chunk_end > total_size:
            self._jsonb_transfer = None
            self._write_frame("ERR", b"BAD_JSONB_LENGTH")
            return None
        transfer["data"][transfer["offset"]:chunk_end] = chunk
        transfer["offset"] = chunk_end
        transfer["next"] += 1
        transfer["wire"] += len(line)
        transfer["updated"] = self._ticks_ms()
        if transfer["next"] < count:
            return None
        if transfer["offset"] != total_size:
            self._jsonb_transfer = None
            self._write_frame("ERR", b"BAD_JSONB_LENGTH")
            return None
        compressed_payload = transfer["data"]
        wire_size = transfer["wire"]
        self._jsonb_transfer = None
        return self._handle_compressed_json_frame(
            compressed_payload, b"", frame_read_calls, receive_elapsed_ms,
            parse_elapsed_ms, "JSONB", False,
            maximum_json_size=SNAPSHOT_TRANSACTION_MAX_BYTES,
            replace_snapshot=True,
            wire_size=wire_size,
        )

    def _handle_compressed_json_frame(
            self, payload, line, frame_read_calls, receive_elapsed_ms,
            parse_elapsed_ms, message_type, base64_encoded,
            maximum_json_size=MAX_JSON_SIZE, replace_snapshot=False,
            wire_size=None,
    ):
        """统一解析压缩 JSON 帧，并按编码类型执行必要的解码。"""
        decompress_started_ms = self._ticks_ms()
        line_size = len(line) if wire_size is None else wire_size
        gc_count = 0

        if base64_encoded:
            try:
                compressed_payload = binascii.a2b_base64(payload)
            except MemoryError as error:
                self._write_frame("ERR", _json_error_payload("MEMORY_BASE64", error))
                return None
            except Exception as error:
                self._write_frame("ERR", _json_error_payload("BASE64", error))
                return None
        else:
            compressed_payload = payload

        # Base64 解码完成后不再需要原始 ASCII 帧；仅在低内存时回收，
        # 正常帧避免承担每次垃圾回收的额外延迟。
        payload = None
        line = None
        gc_count += int(_collect_jsonz_garbage_if_needed())

        try:
            json_payload = decompress_zlib(compressed_payload)
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_ZLIB", error))
            return None
        except (ValueError, OSError, ZLIB_ERROR) as error:
            self._write_frame("ERR", _json_error_payload("ZLIB", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("ZLIB_UNKNOWN", error))
            return None

        # 解压结果已经独立持有 JSON 字节，低内存时在 JSON 解析前释放压缩负载。
        compressed_payload = None
        gc_count += int(_collect_jsonz_garbage_if_needed())

        decompress_elapsed_ms = self._elapsed_ms(
            self._ticks_ms(),
            decompress_started_ms,
        )

        try:
            json_size = len(json_payload)
        except Exception:
            json_size = -1

        if json_size > maximum_json_size:
            self._write_frame(
                "ERR",
                _json_error_payload(
                    "SIZE",
                    detail="JSON_TOO_LARGE:{}>{}".format(
                        json_size,
                        maximum_json_size,
                    ),
                ),
            )
            return None

        try:
            text_payload = json_payload.decode("utf-8")
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_UTF8", error))
            return None
        except UnicodeError as error:
            self._write_frame("ERR", _json_error_payload("UTF8", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("UTF8_UNKNOWN", error))
            return None

        try:
            json_started_ms = self._ticks_ms()
            message = json.loads(text_payload)
            json_elapsed_ms = self._elapsed_ms(
                self._ticks_ms(),
                json_started_ms,
            )
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_JSON_PARSE", error))
            return None
        except ValueError as error:
            self._write_frame("ERR", _json_error_payload("JSON_PARSE", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("JSON_PARSE_UNKNOWN", error))
            return None

        timing = (
            "PROTOCOL_TIMING:TYPE={}:BYTES={}:JSON_BYTES={}:READS={}:"
            "RX={}MS:FRAME_PARSE={}MS:DECOMPRESS={}MS:JSON={}MS:GC={}"
        ).format(
            message_type,
            line_size,
            json_size,
            frame_read_calls,
            receive_elapsed_ms,
            parse_elapsed_ms,
            decompress_elapsed_ms,
            json_elapsed_ms,
            gc_count,
        )
        json_payload = None
        text_payload = None
        try:
            return self._handle_json_message(
                message, timing, payload_size=json_size,
                replace_snapshot=replace_snapshot,
            )
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_JSON_HANDLE", error))
            return None
        except ValueError as error:
            self._write_frame("ERR", _json_error_payload("JSON_HANDLE", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("JSON_HANDLE_UNKNOWN", error))
            return None

    def _handle_json_message(
            self, message, timing=None, payload_size=None,
            replace_snapshot=False,
    ):
        """按 JSON 信封模式分发快照或命令，并兼容旧裸快照。"""
        if not isinstance(message, dict):
            raise ValueError("JSON_OBJECT_REQUIRED")
        mode = message.get("mode")
        if mode == "command":
            self._dispatch_command(message)
            return None
        if mode == "snapshot_chunk":
            snapshot = self._handle_snapshot_chunk(message, payload_size=payload_size)
            if snapshot is None:
                # 事务未收齐，不发送 ACK，也不更新渲染快照。
                return None
            request_id = message.get("request_id")
            self._write_frame(
                "ACK",
                ("JSON:{}".format(request_id) if request_id is not None else "JSON").encode("ascii", "replace"),
            )
            if (snapshot.get("display") or {}).get("dev"):
                # ACK 先返回；开发模式下再报告板端提交开销，便于区分网络与 CPU 慢。
                self._write_frame("EVENT", ("SNAPSHOT_TIMING:" + self._snapshot_commit_timing).encode("ascii"))
            return snapshot
        if mode == "snapshot":
            snapshot = message.get("data")
            if not isinstance(snapshot, dict):
                raise ValueError("SNAPSHOT_DATA_REQUIRED")
        elif mode is None:
            snapshot = message
        else:
            raise ValueError("UNKNOWN_JSON_MODE")
        request_id = message.get("request_id")
        display = snapshot.get("display") or {}
        if display.get("dev") and timing:
            self._write_frame("EVENT", timing.encode("ascii", "replace"))
        ack_payload = "JSON:{}".format(request_id) if request_id is not None else "JSON"
        self._write_frame("ACK", ack_payload.encode("ascii", "replace"))
        self._committed_snapshot = (
            snapshot
            if replace_snapshot
            else self._merge_parsed_snapshots(self._committed_snapshot, snapshot)
        )
        return snapshot

    def _dispatch_command(self, message):
        """延迟创建策略注册表并执行一条 JSON 命令。"""
        from command import create_command_registry
        from command.base import CommandError

        if self._command_registry is None:
            self._command_registry = create_command_registry(
                self._write_command_response,
                self._command_services,
            )
        try:
            self._command_registry.dispatch(message)
        except CommandError as error:
            self._write_command_response({
                "status": "error",
                "command": message.get("command"),
                "error": str(error),
                "request_id": message.get("request_id"),
            })
        except Exception as error:
            self._write_command_response({
                "status": "error",
                "command": message.get("command"),
                "error": "COMMAND_FAILED:{}".format(error),
                "request_id": message.get("request_id"),
            })

    def _write_command_response(self, response):
        """把命令结果编码为 COMMAND 类型的 JSON 响应帧。"""
        self._write_frame(
            "COMMAND",
            json.dumps(response).encode("utf-8"),
        )

    def last_message_ms(self):
        """返回最近一条有效 Monitor 协议消息的接收时刻。"""
        return self._last_message_ms

    def _consume(self, count):
        """重建剩余缓冲区，避免依赖固件对 bytearray 项删除的实现。"""
        if count >= len(self._buffer):
            self._buffer = bytearray()
            self._last_byte_ms = None
            self._frame_started_ms = None
            self._frame_read_calls = 0
        else:
            self._buffer = bytearray(self._buffer[count:])

    def _write_pong(self):
        """返回设备能力、硬件型号、屏幕方案、固件及 SDK 版本。"""
        from lcd import get_lcd_panel_profile
        from styles.style_plugins import style_catalog

        panel_profile = get_lcd_panel_profile(LCD_DEVICE_TYPE)
        transport = self._command_services.get("transport")
        net_status = transport.status() if transport is not None else {
            "mode": "usb" if self._dedicated_stream else "none",
            "connected": True,
        }
        information = {
            "board_model": BOARD_MODEL,
            "device_id": device_uuid(),
            "screen_color_profile": panel_profile.color_profile_name,
            "firmware_version": FIRMWARE_VERSION,
            "sdk_version": runtime_sdk_version(),
            "sdk_update": {
                "supported": sdk_update_supported(),
                "requires_usb": True,
                "image_format": "esp32s3-merged-bin",
            },
            "device_name": DEVICE_NAME,
            "lcd_device_type": LCD_DEVICE_TYPE,
            "lcd_driver": LCD_DRIVER,
            "width": panel_profile.width,
            "height": panel_profile.height,
            "pixel_format": PIXEL_FORMAT,
            "styles": style_catalog(),
            "net": net_status,
        }
        if self._binary_snapshot_supported():
            information["snapshot_chunks"] = {
                "version": 3,
                "encoding": "jsonb",
                "mode": "binary",
                # 单片沿用 PV1/CDC 的 4 KiB 安全预算；完整事务可以更大。
                "max_payload": 4096,
                "max_parts": 4096,
                "max_bytes": SNAPSHOT_TRANSACTION_MAX_BYTES,
            }
        payload = json.dumps(information).encode("utf-8")
        self._write_frame("PONG", payload)

    def _binary_snapshot_supported(self):
        """仅在当前传输明确支持原始二进制时公布 JSONB 能力。"""
        transport = self._command_services.get("transport")
        checker = getattr(transport, "supports_binary_frames", None)
        if callable(checker):
            return bool(checker())
        # 未使用传输管理器的旧调用路径维持原能力；控制台回退路径会通过
        # TransportManager 明确返回 False，避免 REPL 吞掉二进制控制字节。
        return True

    def write_upgrade_response(self, data):
        """把升级状态封装为 PV1 响应帧。"""
        self._write_frame("STATUS", bytes(data).strip())

    @staticmethod
    def _crc16(data):
        """使用字节查表计算 CRC-16/CCITT-FALSE。"""
        crc = 0xFFFF
        for value in data:
            crc = ((crc << 8) & 0xFFFF) ^ CRC16_BYTE_TABLE[((crc >> 8) ^ value) & 0xFF]
        return crc

    @classmethod
    def _build_frame(cls, message_type, payload=b""):
        """构建包含长度和校验值的 PV1 协议帧。"""
        kind = message_type.encode("ascii") if isinstance(message_type, str) else bytes(message_type)
        payload = bytes(payload)
        checksum = cls._crc16(kind + b":" + payload)
        return b":".join((b"PV1", kind, str(len(payload)).encode(), ("%04X" % checksum).encode(), payload)) + b"\n"

    @classmethod
    def _parse_frame(cls, line):
        """优先使用固件原生模块解析 PV1 帧，不支持时回退 Python。"""
        if protocolC.native_protocol_supported():
            return protocolC.parse_frame_native(line, MAX_JSON_SIZE)
        return cls._parse_frame_python(line)

    @classmethod
    def _frame_error_payload(cls, error, line, frame_read_calls=None):
        """生成包含长度现场的帧错误载荷，且不回显业务数据。"""
        error_code = str(error)
        if error_code != "BAD_FRAME_LENGTH":
            return error_code.encode("ascii", "replace")

        line = bytes(line)
        declared_length = None
        remainder_length = None
        separators = []
        search_start = 0
        for _ in range(4):
            separator = line.find(b":", search_start)
            if separator < 0:
                break
            separators.append(separator)
            search_start = separator + 1
        if len(separators) == 4:
            try:
                declared_length = int(
                    line[separators[1] + 1:separators[2]]
                )
            except (TypeError, ValueError):
                declared_length = None
            remainder_length = len(line) - separators[3] - 1

        diagnostics = ["BAD_FRAME_LENGTH"]
        if declared_length is not None:
            diagnostics.append("DECLARED={}".format(declared_length))
        if remainder_length is not None:
            diagnostics.append("REMAINDER={}".format(remainder_length))
        if declared_length is not None and remainder_length is not None:
            shortage = declared_length - remainder_length
            if shortage > 0:
                diagnostics.append("SHORTAGE={}".format(shortage))
        if declared_length is not None and declared_length > MAX_JSON_SIZE:
            diagnostics.append(
                "OVER_LIMIT={}".format(declared_length - MAX_JSON_SIZE)
            )
        diagnostics.extend((
            "MAX={}".format(MAX_JSON_SIZE),
            "LINE_BYTES={}".format(len(line)),
        ))
        if frame_read_calls is not None:
            diagnostics.append("READS={}".format(frame_read_calls))
        diagnostics.append("BACKEND={}".format(cls.protocol_backend()))
        return ":".join(diagnostics).encode("ascii", "replace")

    @classmethod
    def _parse_frame_python(cls, line):
        """使用兼容旧 UF2 的纯 Python 路径校验并解析 PV1 帧。"""
        parts = bytes(line).split(b":", 4)
        if len(parts) != 5 or parts[0] != b"PV1":
            raise ValueError("BAD_FRAME_HEADER")
        try:
            length = int(parts[2])
            expected_crc = int(parts[3], 16)
        except ValueError:
            raise ValueError("BAD_FRAME_HEADER")
        remainder = parts[4]
        if length < 0 or length > MAX_JSON_SIZE or len(remainder) < length:
            raise ValueError("BAD_FRAME_LENGTH")
        payload = remainder[:length]
        if remainder[length:].strip(b" "):
            raise ValueError("BAD_FRAME_TRAILER")
        if cls._crc16(parts[1] + b":" + payload) != expected_crc:
            raise ValueError("BAD_FRAME_CRC")
        try:
            message_type = parts[1].decode("ascii")
        except UnicodeError:
            raise ValueError("BAD_FRAME_TYPE")
        return message_type, payload

    def _write_frame(self, message_type, payload=b""):
        """构建并发送指定类型的 PV1 协议帧。"""
        self._write_raw(self._build_frame(message_type, payload))

    @staticmethod
    def _ticks_ms():
        """返回适用于当前运行环境的单调毫秒时钟。"""
        ticks_ms = getattr(time, "ticks_ms", None)
        return ticks_ms() if ticks_ms else int(time.monotonic() * 1000)

    @staticmethod
    def _elapsed_ms(now, started):
        """计算支持 MicroPython 时钟回绕的毫秒间隔。"""
        if started is None:
            return 0
        ticks_diff = getattr(time, "ticks_diff", None)
        return ticks_diff(now, started) if ticks_diff else now - started

    def _expire_partial_frame(self):
        """丢弃超过一秒没有新字节的半包，恢复协议同步。"""
        transfer = getattr(self, "_jsonb_transfer", None)
        if transfer is not None and self._elapsed_ms(
                self._ticks_ms(), transfer.get("updated"),
        ) >= 10000:
            # 缺片连接即使仍能发送其它消息，也不能无限持有大块压缩缓冲。
            self._jsonb_transfer = None
            self._write_frame("ERR", b"JSONB_TIMEOUT")
        # 物理半包超时检查发生在本轮读取前；CDC 中已有字节时必须先消费，
        # 不能把可继续完成的半包误判为静默超时。
        if self._input_available():
            return
        if not self._buffer or self._last_byte_ms is None:
            return
        now = self._ticks_ms()
        ticks_diff = getattr(time, "ticks_diff", None)
        idle_ms = ticks_diff(now, self._last_byte_ms) if ticks_diff else now - self._last_byte_ms
        if idle_ms >= 1000:
            self._buffer = bytearray()
            self._last_byte_ms = None
            self._frame_started_ms = None
            self._frame_read_calls = 0
            self._write_frame("ERR", b"FRAME_TIMEOUT")

    def _synchronize_magic(self):
        """丢弃魔数之前的串口探测垃圾，并保留可能的魔数前缀。"""
        start = self._buffer.find(b"PV1:")
        if start > 0:
            self._buffer = bytearray(self._buffer[start:])
            self._frame_started_ms = self._ticks_ms()
            self._frame_read_calls = 1
        elif start == 0 and self._frame_started_ms is None:
            self._frame_started_ms = self._ticks_ms()
        elif start < 0 and len(self._buffer) > 3:
            self._buffer = bytearray(self._buffer[-3:])
