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
JSONZ_GC_FREE_THRESHOLD = 72 * 1024


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
    """增量接收 ASCII 行，避免二进制控制字节触发 MicroPython 中断。"""

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

    def is_busy(self):
        """判断串口是否有待接收字节或未完成的行。"""
        return bool(self._buffer) or self._input_available()

    def _input_available(self):
        """兼容策略流和系统流，判断是否存在可立即读取的数据。"""
        available = getattr(self._input, "available", None)
        if callable(available):
            return bool(available())
        return bool(self._poller.poll(0))

    def _parse_lines(self):
        """依次解析已完整接收的命令行，并保留最后一个 JSON。"""
        latest = None
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break

            # memoryview 避免 bytearray 切片先复制一次整包数据，降低解析峰值内存。
            line_view = memoryview(self._buffer)[:newline]
            line = bytes(line_view)
            del line_view

            receive_finished_ms = self._ticks_ms()
            receive_elapsed_ms = self._elapsed_ms(
                receive_finished_ms,
                self._frame_started_ms,
            )
            frame_read_calls = self._frame_read_calls
            self._consume(newline + 1)

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
                self._write_pong()
            elif message_type == "JSONZ":
                latest = self._handle_jsonz_frame(
                    payload=payload,
                    line=line,
                    frame_read_calls=frame_read_calls,
                    receive_elapsed_ms=receive_elapsed_ms,
                    parse_elapsed_ms=parse_elapsed_ms,
                )
            else:
                self._write_frame("ERR", b"UNKNOWN_TYPE")
        return latest

    def _handle_jsonz_frame(
            self,
            payload,
            line,
            frame_read_calls,
            receive_elapsed_ms,
            parse_elapsed_ms,
    ):
        """分阶段解析 JSONZ，并返回更具体的 BAD_JSON 错误。"""
        decompress_started_ms = self._ticks_ms()
        line_size = len(line)
        gc_count = 0

        try:
            compressed_payload = binascii.a2b_base64(payload)
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_BASE64", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("BASE64", error))
            return None

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

        if json_size > MAX_JSON_SIZE:
            self._write_frame(
                "ERR",
                _json_error_payload(
                    "SIZE",
                    detail="JSON_TOO_LARGE:{}>{}".format(
                        json_size,
                        MAX_JSON_SIZE,
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
            "PROTOCOL_TIMING:TYPE=JSONZ:BYTES={}:JSON_BYTES={}:READS={}:"
            "RX={}MS:FRAME_PARSE={}MS:DECOMPRESS={}MS:JSON={}MS:GC={}"
        ).format(
            line_size,
            json_size,
            frame_read_calls,
            receive_elapsed_ms,
            parse_elapsed_ms,
            decompress_elapsed_ms,
            json_elapsed_ms,
            gc_count,
        )
        try:
            return self._handle_json_message(message, timing)
        except MemoryError as error:
            self._write_frame("ERR", _json_error_payload("MEMORY_JSON_HANDLE", error))
            return None
        except ValueError as error:
            self._write_frame("ERR", _json_error_payload("JSON_HANDLE", error))
            return None
        except Exception as error:
            self._write_frame("ERR", _json_error_payload("JSON_HANDLE_UNKNOWN", error))
            return None

    def _handle_json_message(self, message, timing=None):
        """按 JSON 信封模式分发快照或命令，并兼容旧裸快照。"""
        if not isinstance(message, dict):
            raise ValueError("JSON_OBJECT_REQUIRED")
        mode = message.get("mode")
        if mode == "command":
            self._dispatch_command(message)
            return None
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
        """返回设备能力、硬件型号、屏幕方案、固件版本及网络状态。"""
        from lcd import get_lcd_panel_profile
        from styles.style_plugins import style_catalog

        panel_profile = get_lcd_panel_profile(LCD_DEVICE_TYPE)
        transport = self._command_services.get("transport")
        net_status = transport.status() if transport is not None else {
            "mode": "usb" if self._dedicated_stream else "none",
            "connected": True,
        }
        payload = json.dumps({
            "board_model": BOARD_MODEL,
            "screen_color_profile": panel_profile.color_profile_name,
            "firmware_version": FIRMWARE_VERSION,
            "device_name": DEVICE_NAME,
            "lcd_device_type": LCD_DEVICE_TYPE,
            "lcd_driver": LCD_DRIVER,
            "width": panel_profile.width,
            "height": panel_profile.height,
            "pixel_format": PIXEL_FORMAT,
            "styles": style_catalog(),
            "net": net_status,
        }).encode("utf-8")
        self._write_frame("PONG", payload)

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
