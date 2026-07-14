"""按开发板能力创建 PV1 使用的 USB 双工数据流。"""

import gc
import sys
import time

try:
    import uselect as select
except ImportError:
    import select

from config import (
    BOARD_MODEL,
    USB_CDC_ENUMERATION_TIMEOUT_MS,
    USB_CDC_RX_BUFFER_SIZE,
    USB_CDC_TX_BUFFER_SIZE,
)


_ESP32_USB_SESSION_TIMEOUT_MS = 5000


def _ticks_ms():
    """返回兼容 MicroPython 与 CPython 的单调毫秒时钟。"""
    getter = getattr(time, "ticks_ms", None)
    if callable(getter):
        return getter()
    return int(time.monotonic() * 1000)


def _ticks_diff(newer, older):
    """计算兼容 MicroPython 环绕时钟的毫秒差值。"""
    calculator = getattr(time, "ticks_diff", None)
    if callable(calculator):
        return calculator(newer, older)
    return newer - older


class UsbCapabilityStrategy:
    """定义不同开发板创建 USB 数据流的能力策略接口。"""

    name = None

    def create_stream(self, timeout_ms, wait_for_open, **options):
        """创建符合统一读写接口的 USB 数据流。"""
        raise NotImplementedError


class Rp2040UsbDeviceCapability(UsbCapabilityStrategy):
    """使用 RP2040 的 machine.USBDevice 注册独立数据 CDC。"""

    name = "rp2040_usb_device"

    def create_stream(self, timeout_ms, wait_for_open, **options):
        """创建保留 REPL 且独立承载 PV1 的 RP2040 CDC 接口。"""
        del options
        try:
            import machine
        except ImportError as error:
            raise RuntimeError("RP2040_USB_DEVICE_CAPABILITY_UNAVAILABLE") from error
        if not hasattr(machine, "USBDevice"):
            raise RuntimeError("RP2040_USB_DEVICE_CAPABILITY_UNAVAILABLE")
        try:
            import usb.device
            from usb.device.cdc import CDCInterface
        except (ImportError, AttributeError) as error:
            raise RuntimeError("MICROPYTHON_1_23_OR_NEWER_REQUIRED") from error

        cdc = CDCInterface(
            timeout=0,
            txbuf=USB_CDC_TX_BUFFER_SIZE,
            rxbuf=USB_CDC_RX_BUFFER_SIZE,
        )
        usb.device.get().init(
            cdc,
            builtin_driver=True,
            manufacturer_str="Pico Vision",
            product_str="Pico Vision REPL + Data",
        )
        if wait_for_open:
            deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
            while not cdc.is_open():
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    raise RuntimeError("USB_DATA_CDC_ENUMERATION_TIMEOUT")
                time.sleep_ms(20)
        gc.collect()
        return cdc


class Esp32BuiltinUsbStream:
    """把 ESP32-S3 固件内置 USB 控制台适配为统一二进制双工流。"""

    def __init__(
        self,
        input_stream=None,
        output_stream=None,
        session_timeout_ms=_ESP32_USB_SESSION_TIMEOUT_MS,
    ):
        """保存控制台输入输出，并创建首字节连接检测轮询器。"""
        self._input = sys.stdin if input_stream is None else input_stream
        self._reader = getattr(self._input, "buffer", self._input)
        self._output = sys.stdout if output_stream is None else output_stream
        self._writer = getattr(self._output, "buffer", self._output)
        self._session_timeout_ms = max(1, int(session_timeout_ms))
        self._connected = False
        self._last_activity_ms = None
        self._poller = select.poll()
        self._poller.register(self._input, select.POLLIN)

    def poll_target(self):
        """返回必须用于检测可读事件的 ESP32 控制台文本流。"""
        return self._input

    def _mark_activity(self):
        """记录 USB 会话活动并保持当前连接锁定。"""
        self._connected = True
        self._last_activity_ms = _ticks_ms()

    def is_open(self):
        """收到首个字节后报告连接，并在长期无活动时释放会话。"""
        if self._poller.poll(0):
            self._mark_activity()
        elif self._connected and self._last_activity_ms is not None:
            if _ticks_diff(_ticks_ms(), self._last_activity_ms) >= self._session_timeout_ms:
                self._connected = False
                self._last_activity_ms = None
        return self._connected

    def readinto(self, buffer):
        """批量读取控制台已有字节，旧版固件回退为单字节非阻塞读取。"""
        if not buffer:
            return 0
        # 定制固件在 C 层一次抽干当前已经到达的控制台 FIFO，既减少 Python
        # 调用次数，又不会等待缓冲区填满。标准固件没有该接口时，仍只传入
        # 一个字节的视图，规避旧版 ESP32 MicroPython 的阻塞式 readinto()。
        nonblocking_reader = getattr(self._reader, "readinto_nonblocking", None)
        if callable(nonblocking_reader):
            count = int(nonblocking_reader(buffer) or 0)
            if count > 0:
                self._mark_activity()
            return count

        target = memoryview(buffer)[:1]
        reader = getattr(self._reader, "readinto", None)
        if callable(reader):
            count = reader(target)
        else:
            data = self._reader.read(1)
            if isinstance(data, str):
                data = data.encode("utf-8")
            count = len(data or b"")
            if count:
                target[:count] = data
        count = int(count or 0)
        if count > 0:
            self._mark_activity()
        return count

    def write(self, data):
        """通过 ESP32 内置控制台发送二进制 PV1 数据。"""
        try:
            written = self._writer.write(data)
        except TypeError:
            self._writer.write(bytes(data).decode("utf-8"))
            written = len(data)
        if written is None:
            written = len(data)
        written = int(written)
        if written > 0:
            self._mark_activity()
        return written

    def flush(self):
        """保持内置 USB 控制台非阻塞，其写入本身已经直接提交。"""
        return None

    def close(self):
        """释放 PV1 会话状态但不关闭系统内置控制台。"""
        self._connected = False
        self._last_activity_ms = None


class Esp32S3BuiltinUsbCapability(UsbCapabilityStrategy):
    """使用 ESP32-S3 固件内置 USB CDC 或 USB 串行控制台。"""

    name = "esp32_s3_builtin_console"

    def create_stream(self, timeout_ms, wait_for_open, **options):
        """创建 ESP32-S3 内置控制台双工流，不访问 machine.USBDevice。"""
        del timeout_ms, wait_for_open
        return Esp32BuiltinUsbStream(
            input_stream=options.get("input_stream"),
            output_stream=options.get("output_stream"),
            session_timeout_ms=options.get(
                "session_timeout_ms",
                _ESP32_USB_SESSION_TIMEOUT_MS,
            ),
        )


_USB_CAPABILITY_STRATEGIES = {
    "rp2040_usb": Rp2040UsbDeviceCapability(),
    "rp2040_typec": Rp2040UsbDeviceCapability(),
    "esp32-s3": Esp32S3BuiltinUsbCapability(),
}


def get_usb_capability_strategy(board_model):
    """根据开发板型号返回对应 USB 能力策略。"""
    normalized_model = str(board_model or "").strip().lower()
    strategy = _USB_CAPABILITY_STRATEGIES.get(normalized_model)
    if strategy is None:
        raise ValueError("未知开发板 USB 能力：{}".format(board_model))
    return strategy


def create_usb_stream(
    board_model=BOARD_MODEL,
    timeout_ms=USB_CDC_ENUMERATION_TIMEOUT_MS,
    wait_for_open=True,
    **options
):
    """按照 config.py 的开发板型号创建对应 USB 数据流。"""
    strategy = get_usb_capability_strategy(board_model)
    return strategy.create_stream(timeout_ms, wait_for_open, **options)


def create_data_cdc(
    timeout_ms=USB_CDC_ENUMERATION_TIMEOUT_MS,
    wait_for_open=True,
):
    """兼容旧调用并固定创建 RP2040 独立数据 CDC。"""
    return Rp2040UsbDeviceCapability().create_stream(
        timeout_ms,
        wait_for_open,
    )
