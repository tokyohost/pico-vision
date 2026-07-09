"""USB CDC 底层读写线程框架。"""

import logging
import queue
import threading
import time

import serial


LOGGER = logging.getLogger("pico-monitor.serial")
CDC_WRITE_CHUNK_SIZE = 511
CDC_READ_IDLE_SECONDS = 0.05
CDC_WRITE_RETRY_SECONDS = 0.002


class UsbCdcFrameworkClosed(RuntimeError):
    """表示 USB CDC 读写框架已经关闭或串口不可用。"""


class UsbCdcWriteResult:
    """记录一次 USB CDC 写入任务的完整耗时统计。"""

    def __init__(self, label, total_bytes, build_elapsed_ms=0.0):
        """初始化写入标签、目标字节数和构帧耗时。"""
        self.label = label
        self.total_bytes = total_bytes
        self.build_elapsed_ms = build_elapsed_ms
        self.send_started = None
        self.send_finished = None
        self.write_elapsed_ms = 0.0
        self.slowest_write_ms = 0.0
        self.flush_elapsed_ms = 0.0
        self.send_elapsed_ms = 0.0
        self.total_written = 0
        self.chunk_count = 0

    def as_dict(self):
        """转换为 PicoJsonClient 兼容的发送耗时字典。"""
        return {
            "build_elapsed_ms": self.build_elapsed_ms,
            "send_started": self.send_started,
            "send_finished": self.send_finished,
            "send_elapsed_ms": self.send_elapsed_ms,
            "write_elapsed_ms": self.write_elapsed_ms,
            "slowest_write_ms": self.slowest_write_ms,
            "flush_elapsed_ms": self.flush_elapsed_ms,
            "total_written": self.total_written,
            "chunk_count": self.chunk_count,
        }


class _UsbCdcWriteJob:
    """封装一条待写入 USB CDC 的协议帧。"""

    def __init__(self, packet, label, build_elapsed_ms, timeout):
        """保存待发送数据、日志标签、构帧耗时和等待上限。"""
        self.packet = bytes(packet)
        self.label = label
        self.build_elapsed_ms = build_elapsed_ms
        self.timeout = timeout
        self.done = threading.Event()
        self.result = None
        self.error = None

    def finish(self, result=None, error=None):
        """记录任务完成状态并唤醒等待线程。"""
        self.result = result
        self.error = error
        self.done.set()


class UsbCdcFramework:
    """以独立读写线程管理 USB CDC 串口，降低业务线程被 CDC 背压阻塞的概率。"""

    def __init__(
            self,
            device,
            frame_parser,
            port_name=None,
            response_callback=None,
            error_callback=None,
            write_chunk_size=CDC_WRITE_CHUNK_SIZE,
            incoming_limit=256,
            write_limit=4,
    ):
        """绑定已握手串口并准备有界读写队列。"""
        self.device = device
        self.frame_parser = frame_parser
        self.port_name = port_name or getattr(device, "port", "UNKNOWN")
        self.response_callback = response_callback
        self.error_callback = error_callback
        self.write_chunk_size = int(write_chunk_size)
        self._incoming_queue = queue.Queue(maxsize=max(1, int(incoming_limit)))
        self._write_queue = queue.Queue(maxsize=max(1, int(write_limit)))
        self._stopping = threading.Event()
        self._closed = threading.Event()
        self._state_lock = threading.Lock()
        self._write_idle = threading.Event()
        self._write_idle.set()
        self._last_error = None
        self._reader_thread = None
        self._writer_thread = None

    def start(self):
        """启动 USB CDC 读线程和写线程。"""
        if self._reader_thread is not None:
            return
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            name="usb-cdc-reader",
            daemon=True,
        )
        self._writer_thread = threading.Thread(
            target=self._write_loop,
            name="usb-cdc-writer",
            daemon=True,
        )
        self._reader_thread.start()
        self._writer_thread.start()

    def close(self, wait=True):
        """请求读写线程退出，必要时等待线程结束。"""
        self._stopping.set()
        self._fail_pending_writes(UsbCdcFrameworkClosed("USB CDC 框架已关闭"))
        if wait:
            for thread in (self._writer_thread, self._reader_thread):
                if thread is not None and thread.is_alive():
                    thread.join(timeout=1.0)
        self._closed.set()

    @property
    def is_alive(self):
        """返回读写框架是否仍处于可用状态。"""
        return not self._stopping.is_set() and self._last_error is None

    def raise_error_if_any(self):
        """若后台线程捕获到通信异常，则转交调用线程处理。"""
        with self._state_lock:
            error = self._last_error
            self._last_error = None
        if error is not None:
            raise error

    def write_packet(self, packet, label, build_elapsed_ms=0.0, timeout=1.0):
        """提交一条协议帧到写线程，并等待该帧完成写入。"""
        if self._stopping.is_set():
            raise UsbCdcFrameworkClosed("USB CDC 框架已关闭")
        self.raise_error_if_any()
        job = _UsbCdcWriteJob(packet, label, build_elapsed_ms, max(0.1, float(timeout)))
        try:
            self._write_queue.put(job, timeout=job.timeout)
        except queue.Full as error:
            raise serial.SerialTimeoutException(
                "{} 写入队列已满，USB CDC 仍在背压".format(label)
            ) from error
        if not job.done.wait(job.timeout):
            raise serial.SerialTimeoutException(
                "{} 写入等待超过 {:.1f} 秒".format(label, job.timeout)
            )
        if job.error is not None:
            raise job.error
        return job.result.as_dict()

    def read_frame(self, label, timeout=0.3):
        """从读线程缓存中获取下一条非 JSON ACK 协议帧。"""
        self.raise_error_if_any()
        try:
            return self._incoming_queue.get(timeout=max(0.0, float(timeout)))
        except queue.Empty:
            return None

    def wait_until_write_idle(self, timeout=None):
        """等待写线程完成当前任务，供控制命令切换前同步状态。"""
        return self._write_idle.wait(timeout)

    def _read_loop(self):
        """持续读取 Pico 响应，避免 ACK/ERR/EVENT 堆积在系统 CDC 缓冲中。"""
        while not self._stopping.is_set():
            try:
                raw = self.device.readline()
            except TypeError as error:
                if not getattr(self.device, "is_open", False):
                    self._record_error(serial.SerialException("读取 Pico 响应时串口已关闭"))
                    return
                self._record_error(error)
                return
            except (OSError, serial.SerialException) as error:
                if not self._stopping.is_set():
                    self._record_error(error)
                return
            if not raw:
                time.sleep(CDC_READ_IDLE_SECONDS)
                continue
            response = bytes(raw).strip()
            try:
                frame = self.frame_parser(response)
            except ValueError as error:
                LOGGER.warning(
                    "[Pico -> Monitor][%s][CDC 读线程坏帧] %s raw=%r",
                    self.port_name,
                    error,
                    response,
                )
                self._record_error(RuntimeError("Pico 返回损坏协议帧：{}".format(error)))
                return
            if response and self.response_callback is not None:
                try:
                    self.response_callback("CDC 读线程", response, frame)
                except (OSError, RuntimeError, serial.SerialException) as error:
                    self._record_error(error)
                    return
            if self._is_json_ack(frame):
                continue
            if frame and frame[0] == "ERR":
                if self.error_callback is not None and self.error_callback(frame):
                    continue
            self._put_incoming_frame(frame)

    def _write_loop(self):
        """串行处理写入任务，控制 USB CDC 背压只影响写线程。"""
        while not self._stopping.is_set():
            try:
                job = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._write_idle.clear()
            try:
                result = self._perform_write(job)
                job.finish(result=result)
            except (OSError, RuntimeError, serial.SerialException) as error:
                job.finish(error=error)
                self._record_error(error)
                return
            finally:
                self._write_queue.task_done()
                if self._write_queue.empty():
                    self._write_idle.set()

    def _perform_write(self, job):
        """按固定大小分块写入串口，短写或零写入时短暂退避重试。"""
        packet = memoryview(job.packet)
        result = UsbCdcWriteResult(job.label, len(packet), job.build_elapsed_ms)
        result.send_started = time.monotonic()
        deadline = result.send_started + job.timeout
        position = 0
        while position < len(packet):
            if time.monotonic() >= deadline:
                raise serial.SerialTimeoutException(
                    "{} 发送超过 {:.1f} 秒".format(job.label, job.timeout)
                )
            chunk = packet[position:position + self.write_chunk_size]
            write_started = time.monotonic()
            try:
                written = self.device.write(chunk)
            except serial.SerialTimeoutException:
                time.sleep(CDC_WRITE_RETRY_SECONDS)
                continue
            chunk_elapsed_ms = (time.monotonic() - write_started) * 1000
            result.write_elapsed_ms += chunk_elapsed_ms
            result.slowest_write_ms = max(result.slowest_write_ms, chunk_elapsed_ms)
            result.chunk_count += 1
            if written is None:
                written = len(chunk)
            if written < 0:
                raise serial.SerialTimeoutException("{} 写入返回负数".format(job.label))
            if written == 0:
                time.sleep(CDC_WRITE_RETRY_SECONDS)
                continue
            position += written
            result.total_written += written
        flush_started = time.monotonic()
        self.device.flush()
        result.flush_elapsed_ms = (time.monotonic() - flush_started) * 1000
        result.send_finished = time.monotonic()
        result.send_elapsed_ms = (result.send_finished - result.send_started) * 1000
        return result

    def _put_incoming_frame(self, frame):
        """保存非 ACK 响应；满队列时丢弃最旧响应以保持读线程通畅。"""
        try:
            self._incoming_queue.put_nowait(frame)
            return
        except queue.Full:
            try:
                self._incoming_queue.get_nowait()
            except queue.Empty:
                pass
            self._incoming_queue.put_nowait(frame)

    def _fail_pending_writes(self, error):
        """将尚未执行的写入任务全部标记为失败。"""
        while True:
            try:
                job = self._write_queue.get_nowait()
            except queue.Empty:
                return
            job.finish(error=error)
            self._write_queue.task_done()

    def _record_error(self, error):
        """记录后台通信异常并唤醒所有等待者。"""
        with self._state_lock:
            self._last_error = error
        self._stopping.set()
        self._fail_pending_writes(error)
        self._write_idle.set()

    @staticmethod
    def _is_json_ack(frame):
        """判断帧是否为 JSONZ 快照确认。"""
        if not frame or frame[0] != "ACK":
            return False
        payload = frame[1].decode("ascii", errors="replace")
        return payload == "JSON" or payload.startswith("JSON:")
