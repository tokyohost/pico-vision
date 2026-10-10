"""记录 USB CDC 主机写入吞吐和接收超时，提供有依据的连接排查提示。"""

import logging
import threading
import time
from collections import deque


LOGGER = logging.getLogger("pico-monitor.serial")
USB_DIAGNOSTIC_WINDOW_SECONDS = 30.0
USB_DIAGNOSTIC_HINT_INTERVAL_SECONDS = 60.0
USB_DIAGNOSTIC_REPEAT_COUNT = 3
USB_LOW_WRITE_RATE_BYTES_PER_SECOND = 4096
USB_DIAGNOSTIC_MIN_FRAME_BYTES = 1024
USB_LONG_WRITE_MILLISECONDS = 1000


class UsbTransferDiagnostics:
    """按连接统计最近的慢写和 FRAME_TIMEOUT，避免将单次延迟误判为线材故障。"""

    def __init__(self):
        """初始化供读写线程共享的诊断窗口和提示冷却时间。"""
        self._lock = threading.Lock()
        self._slow_writes = deque(maxlen=64)
        self._frame_timeouts = deque(maxlen=64)
        self._last_write = None
        self._last_hint_time = None

    def reset(self):
        """断开连接时清空统计，防止旧设备的异常影响下一次连接。"""
        with self._lock:
            self._slow_writes.clear()
            self._frame_timeouts.clear()
            self._last_write = None
            self._last_hint_time = None

    @staticmethod
    def _trim_window(events, now):
        """移除三十秒窗口之外的异常，限制过期事件对提示的影响。"""
        while events and now - events[0] > USB_DIAGNOSTIC_WINDOW_SECONDS:
            events.popleft()

    def _warn_if_repeated(self, port, reason, now):
        """异常达到阈值时提供排查建议，每个连接至多每分钟提示一次。"""
        if self._last_hint_time is not None and now - self._last_hint_time < USB_DIAGNOSTIC_HINT_INTERVAL_SECONDS:
            return
        self._last_hint_time = now
        LOGGER.warning(
            "[USB 链路排查][%s] %s；建议先直连电脑 USB 接口、尝试更换可靠的数据线；"
            "若仍异常，请检查 USB 驱动及设备接收、渲染负载。仅凭吞吐和超时不能判定数据线故障。",
            port, reason,
        )

    def record_write(self, port, label, timing):
        """记录主机侧有效写入速率，连续慢写时提示排查 USB 连接。"""
        elapsed_ms = float(timing.get("send_elapsed_ms", 0))
        written = int(timing.get("total_written", 0))
        if elapsed_ms <= 0 or written <= 0:
            return
        # write 完成表示驱动接受写入，不能把这个速率当作线材物理速率或设备已接收证明。
        rate = written * 1000.0 / elapsed_ms
        longest_ms = float(timing.get("slowest_write_ms", 0))
        now = timing.get("send_finished")
        if now is None:
            now = time.monotonic()
        with self._lock:
            self._last_write = (now, label, written, elapsed_ms, rate, longest_ms)
            self._trim_window(self._slow_writes, now)
            LOGGER.debug(
                "[USB 写入吞吐][%s][%s] 主机有效写入=%.2f KiB/s，字节=%d，"
                "发送阶段=%.1f ms，最慢write=%.1f ms；此值不代表线材物理速率",
                port, label, rate / 1024, written, elapsed_ms, longest_ms,
            )
            slow = written >= USB_DIAGNOSTIC_MIN_FRAME_BYTES and (
                rate < USB_LOW_WRITE_RATE_BYTES_PER_SECOND or longest_ms >= USB_LONG_WRITE_MILLISECONDS
            )
            if not slow:
                self._slow_writes.clear()
                return
            self._slow_writes.append(now)
            if len(self._slow_writes) >= USB_DIAGNOSTIC_REPEAT_COUNT:
                self._warn_if_repeated(
                    port, "30 秒内连续慢写 {} 次，最近主机有效写入 {:.2f} KiB/s，最慢write {:.1f} ms".format(
                        len(self._slow_writes), rate / 1024, longest_ms,
                    ), now,
                )

    def record_frame_timeout(self, port, firmware_version=None, sdk_version=None):
        """记录设备半帧超时，并附上最近写入数据用于区分低速和接收丢帧。"""
        now = time.monotonic()
        with self._lock:
            self._trim_window(self._frame_timeouts, now)
            self._frame_timeouts.append(now)
            last = self._last_write
            detail = "最近 30 秒没有已完成写入的吞吐记录"
            if last is not None and now - last[0] <= USB_DIAGNOSTIC_WINDOW_SECONDS:
                _, label, written, elapsed_ms, rate, longest_ms = last
                detail = "最近帧 {}：{} 字节/{:.1f} ms，主机有效写入 {:.2f} KiB/s，最慢write {:.1f} ms".format(
                    label, written, elapsed_ms, rate / 1024, longest_ms,
                )
            LOGGER.warning(
                "[USB 接收超时诊断][%s] 固件=%s，SDK=%s，30 秒内 FRAME_TIMEOUT=%d 次；%s；"
                "主机写入完成不代表设备收到完整帧，需结合控制线重配置及设备接收状态排查",
                port, firmware_version or "未知", sdk_version or "未知", len(self._frame_timeouts), detail,
            )
            if len(self._frame_timeouts) >= USB_DIAGNOSTIC_REPEAT_COUNT:
                self._warn_if_repeated(port, "30 秒内 FRAME_TIMEOUT {} 次；{}".format(
                    len(self._frame_timeouts), detail,
                ), now)
