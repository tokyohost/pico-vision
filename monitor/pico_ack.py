#  Copyright (c) 2026 xuehui_li
#
#  Licensed under the Custom Non-Commercial Copyleft License.
#  Commercial use is prohibited without prior written permission.

"""管理 JSON 快照 ACK 的等待、唤醒和端到端耗时记录。"""

import logging
import threading
import time

from pico_protocol import JsonAckTimeoutError, PicoRestartingError, is_restarting_fatal


LOGGER = logging.getLogger("pico-monitor.serial")


class PicoJsonAckMixin:
    """为 Pico 客户端提供 JSON ACK 状态机。"""

    def _next_json_request_id(self):
        """生成进程内单调递增的 JSON 快照请求序号。"""
        self._json_request_sequence = (self._json_request_sequence + 1) & 0x7FFFFFFF
        return self._json_request_sequence

    def _begin_json_ack_timing(self, request_id, build_started, build_elapsed_ms):
        """在写入前登记请求序号，避免 ACK 读线程先到导致耗时未知。"""
        self._json_ack_pending.put(request_id, {
            "created_at": build_started,
            "build_started": build_started,
            "send_started": time.monotonic(),
            "send_finished": None,
            "build_elapsed_ms": build_elapsed_ms,
            "send_elapsed_ms": 0.0,
        })

    def _complete_json_ack_timing(self, request_id, build_started, write_timing):
        """补全 JSON 快照发送时间，用于异步 ACK 到达时计算端到端耗时。"""
        self._json_ack_pending.update(request_id, {
            "build_started": build_started,
            "send_started": write_timing["send_started"],
            "send_finished": write_timing["send_finished"],
            "build_elapsed_ms": write_timing["build_elapsed_ms"],
            "send_elapsed_ms": write_timing["send_elapsed_ms"],
        })

    def _format_json_ack_timing_suffix(self, frame, received_at):
        """为 JSON ACK 响应日志生成发送到确认的耗时说明。"""
        if not frame or frame[0] != "ACK":
            return ""
        payload = frame[1].decode("ascii", errors="replace")
        if payload != "JSON" and not payload.startswith("JSON:"):
            return ""
        request_id = payload.split(":", 1)[1] if ":" in payload else None
        inferred = False
        if request_id is not None:
            timing = self._json_ack_pending.pop(request_id)
        else:
            request_id, timing = self._json_ack_pending.pop_oldest()
            inferred = timing is not None
        if timing is None:
            pending_snapshot = self._json_ack_pending.snapshot()
            if request_id is None:
                return "，发送到收到ACK耗时=未知，ACK缓存={}".format(pending_snapshot)
            return "，request_id={}，发送到收到ACK耗时=未知，ACK缓存={}".format(
                request_id,
                pending_snapshot,
            )
        send_to_ack_ms = (received_at - timing["send_started"]) * 1000
        build_to_ack_ms = (received_at - timing["build_started"]) * 1000
        request_text = "{}{}".format(request_id, "（推断）" if inferred else "")
        if timing.get("send_finished") is None:
            return (
                "，request_id={}，发送到收到ACK耗时={:.1f} ms，写完到ACK=未知，"
                "构帧到ACK={:.1f} ms，构帧={:.1f} ms，发送阶段=进行中"
            ).format(
                request_text,
                send_to_ack_ms,
                build_to_ack_ms,
                timing["build_elapsed_ms"],
            )
        write_done_to_ack_ms = (received_at - timing["send_finished"]) * 1000
        return (
            "，request_id={}，发送到收到ACK耗时={:.1f} ms，写完到ACK={:.1f} ms，"
            "构帧到ACK={:.1f} ms，构帧={:.1f} ms，发送阶段={:.1f} ms"
        ).format(
            request_text,
            send_to_ack_ms,
            write_done_to_ack_ms,
            build_to_ack_ms,
            timing["build_elapsed_ms"],
            timing["send_elapsed_ms"],
        )

    @staticmethod
    def _json_ack_request_id(frame):
        """从 JSON ACK 帧中解析请求序号；旧固件无序号时返回空值。"""
        if not frame or frame[0] != "ACK":
            return None
        payload = frame[1].decode("ascii", errors="replace")
        if payload == "JSON":
            return None
        if payload.startswith("JSON:"):
            return payload.split(":", 1)[1]
        return None

    def _register_json_ack_waiter(self, request_id):
        """为指定 JSON 请求创建 ACK 等待事件。"""
        event = threading.Event()
        with self._json_ack_lock:
            self._json_ack_events[str(request_id)] = event
        return event

    def _remove_json_ack_waiter(self, request_id):
        """清理指定 JSON 请求的 ACK 等待事件。"""
        with self._json_ack_lock:
            self._json_ack_events.pop(str(request_id), None)

    def _notify_json_ack(self, frame):
        """在 CDC 读线程收到 JSON ACK 时唤醒等待发送线程。"""
        if not frame or frame[0] != "ACK":
            return
        payload = frame[1].decode("ascii", errors="replace")
        if payload != "JSON" and not payload.startswith("JSON:"):
            return
        request_id = self._json_ack_request_id(frame)
        with self._json_ack_lock:
            if request_id is None:
                events = list(self._json_ack_events.values())
            else:
                event = self._json_ack_events.get(str(request_id))
                events = [event] if event is not None else []
        for event in events:
            event.set()

    def _wait_json_ack(self, request_id, event, timeout):
        """等待 Pico 确认指定 JSON 快照，期间持续转交 CDC 后台异常。"""
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() < deadline:
            if self.transport is None:
                frame = self._read_protocol_frame("JSONZ ACK")
                if frame and frame[0] == "ACK":
                    ack_request_id = self._json_ack_request_id(frame)
                    if ack_request_id is None or str(ack_request_id) == str(request_id):
                        return
                if is_restarting_fatal(frame):
                    raise PicoRestartingError(frame[1].decode("utf-8", errors="replace"))
                if frame and frame[0] == "ERR":
                    raise RuntimeError(frame[1].decode("utf-8", errors="replace"))
                continue
            if event.wait(min(0.1, max(0.0, deadline - time.monotonic()))):
                return
            self.transport.raise_error_if_any()
        raise JsonAckTimeoutError("等待 JSON ACK 超时：request_id={}".format(request_id))

    def _drain_json_responses(self):
        """非阻塞消费已经到达的 JSON 响应，避免 ACK 反向缓存持续积压。"""
        if self.transport is not None:
            self.transport.raise_error_if_any()
            while True:
                frame = self.transport.read_frame("JSONZ 异步响应", timeout=0.0)
                if not frame:
                    return
                if frame[0] == "ACK" and frame[1].startswith(b"JSON"):
                    continue
                if frame[0] == "ERR":
                    LOGGER.warning(
                        "[JSONZ 异步错误][%s] %s",
                        self.port_name,
                        frame[1].decode("utf-8", errors="replace"),
                    )
                elif is_restarting_fatal(frame):
                    raise PicoRestartingError("Pico 发生不可恢复的渲染错误，设备正在自动重启")
        device = self.serial
        while device is not None and getattr(device, "in_waiting", 0) > 0:
            frame = self._read_protocol_frame("JSONZ 异步响应")
            if not frame:
                continue
            if frame[0] == "ACK" and frame[1].startswith(b"JSON"):
                continue
            if frame[0] == "ERR":
                LOGGER.warning(
                    "[JSONZ 异步错误][%s] %s",
                    self.port_name,
                    frame[1].decode("utf-8", errors="replace"),
                )
            elif is_restarting_fatal(frame):
                raise PicoRestartingError("Pico 发生不可恢复的渲染错误，设备正在自动重启")
