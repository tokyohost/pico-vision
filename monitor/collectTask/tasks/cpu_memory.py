"""CPU 和内存采集任务。"""

import ctypes
import logging
import platform
import time

import psutil

from history import update_per_second

from ..system_tasks import CollectionTask


CPU_SAMPLE_WINDOW_SECONDS = 0.5
LOGGER = logging.getLogger("pico-monitor.collector")


class _PdhFormattedValueUnion(ctypes.Union):
    """保存 Windows PDH 格式化计数器的联合值。"""

    _fields_ = [("double_value", ctypes.c_double), ("large_value", ctypes.c_longlong)]


class _PdhFormattedValue(ctypes.Structure):
    """描述 Windows PDH 格式化计数器值及状态。"""

    _anonymous_ = ("value",)
    _fields_ = [("status", ctypes.c_ulong), ("value", _PdhFormattedValueUnion)]


class _WindowsPdhCpuSampler:
    """通过 Windows PDH 读取更接近任务管理器口径的 CPU 使用率。"""

    _PDH_DOUBLE = 0x00000200
    _COUNTER_PATHS = (
        r"\Processor Information(_Total)\% Processor Utility",
        r"\Processor(_Total)\% Processor Time",
    )

    def __init__(self):
        """初始化 PDH 查询，并优先使用 Processor Utility 计数器。"""
        if platform.system() != "Windows":
            raise OSError("PDH CPU 采样仅支持 Windows")
        self.library = ctypes.WinDLL("pdh.dll")
        self.query = ctypes.c_void_p()
        self.counter = ctypes.c_void_p()
        self.counter_path = None
        self._configure_functions()
        self._open_first_available_counter()

    def _configure_functions(self):
        """声明当前使用的 PDH 函数参数与返回类型。"""
        self.library.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.library.PdhOpenQueryW.restype = ctypes.c_ulong
        self.library.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
        self.library.PdhAddEnglishCounterW.restype = ctypes.c_ulong
        self.library.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self.library.PdhCollectQueryData.restype = ctypes.c_ulong
        self.library.PdhGetFormattedCounterValue.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(_PdhFormattedValue)]
        self.library.PdhGetFormattedCounterValue.restype = ctypes.c_ulong
        self.library.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        self.library.PdhCloseQuery.restype = ctypes.c_ulong

    def _open_first_available_counter(self):
        """按优先级打开第一个可用 CPU 计数器。"""
        for path in self._COUNTER_PATHS:
            query = ctypes.c_void_p()
            counter = ctypes.c_void_p()
            if self.library.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
                continue
            if self.library.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) == 0:
                self.query = query
                self.counter = counter
                self.counter_path = path
                self.library.PdhCollectQueryData(self.query)
                return
            self.library.PdhCloseQuery(query)
        raise OSError("Windows CPU PDH 计数器不可用")

    def sample(self, sample_window_seconds):
        """通过指定阻塞窗口采样并返回 CPU 使用率百分比。"""
        if self.library.PdhCollectQueryData(self.query) != 0:
            return None
        time.sleep(max(0.0, float(sample_window_seconds)))
        if self.library.PdhCollectQueryData(self.query) != 0:
            return None
        value_type = ctypes.c_ulong()
        value = _PdhFormattedValue()
        status = self.library.PdhGetFormattedCounterValue(
            self.counter,
            self._PDH_DOUBLE,
            ctypes.byref(value_type),
            ctypes.byref(value),
        )
        if status != 0 or value.status != 0:
            return None
        return max(0.0, min(100.0, float(value.double_value)))

    def close(self):
        """关闭 PDH 查询句柄。"""
        query = getattr(self, "query", None)
        if query and query.value:
            self.library.PdhCloseQuery(query)
            self.query = ctypes.c_void_p()


class CpuMemoryTask(CollectionTask):
    """采集 CPU、内存、CPU 频率与温度并维护对应历史序列。"""

    name = "cpu_memory"
    zh_name = "CPU与内存采集"
    default_interval = 1.0
    order = 20

    def __init__(self, collector):
        """初始化 CPU 采集任务，并延迟创建 Windows PDH 采样器。"""
        super().__init__(collector)
        self._windows_cpu_sampler = None
        self._windows_cpu_sampler_unavailable = False
        self._cpu_percent_source_logged = False

    def collect(self):
        """通过短阻塞窗口采样 CPU，并返回 CPU 和内存两个顶层指标。"""
        cpu = round(self._cpu_percent(), 1)
        memory = psutil.virtual_memory()
        now = time.monotonic()
        for name, value in (("cpu", cpu), ("memory", memory.percent)):
            update_per_second(
                self.collector.histories[name],
                round(value, 1),
                self.collector.history_states.setdefault(name, {}),
                now,
            )
        return {
            "cpu": {
                "percent": cpu,
                "frequency_ghz": self.collector._cpu_frequency_ghz(),
                "temperature_c": self.collector._cpu_temperature(),
                "history": list(self.collector.histories["cpu"]),
            },
            "memory": {
                "percent": round(memory.percent, 1),
                "used_bytes": memory.used,
                "total_bytes": memory.total,
                "history": list(self.collector.histories["memory"]),
            },
        }

    def _cpu_percent(self):
        """Windows 优先读取 PDH CPU 计数器，失败时回退到 psutil 阻塞采样。"""
        if platform.system() == "Windows" and not self._windows_cpu_sampler_unavailable:
            try:
                if self._windows_cpu_sampler is None:
                    self._windows_cpu_sampler = _WindowsPdhCpuSampler()
                    if not self._cpu_percent_source_logged:
                        LOGGER.info(
                            "Windows CPU 利用率采样源：PDH 计数器 %s，采样窗口=%.1f秒",
                            self._windows_cpu_sampler.counter_path,
                            CPU_SAMPLE_WINDOW_SECONDS,
                        )
                        self._cpu_percent_source_logged = True
                value = self._windows_cpu_sampler.sample(CPU_SAMPLE_WINDOW_SECONDS)
                if value is not None:
                    return value
                LOGGER.warning(
                    "Windows CPU 利用率 PDH 计数器返回空值，回退到 psutil.cpu_percent(interval=%.1f)",
                    CPU_SAMPLE_WINDOW_SECONDS,
                )
            except (AttributeError, OSError, TypeError, ValueError) as error:
                LOGGER.warning(
                    "Windows CPU 利用率 PDH 采样不可用，回退到 psutil.cpu_percent(interval=%.1f)：%s",
                    CPU_SAMPLE_WINDOW_SECONDS,
                    error,
                )
            sampler = self._windows_cpu_sampler
            if sampler is not None:
                sampler.close()
                self._windows_cpu_sampler = None
            self._windows_cpu_sampler_unavailable = True
        if platform.system() == "Windows" and not self._cpu_percent_source_logged:
            LOGGER.info(
                "Windows CPU 利用率采样源：psutil.cpu_percent(interval=%.1f)",
                CPU_SAMPLE_WINDOW_SECONDS,
            )
            self._cpu_percent_source_logged = True
        return psutil.cpu_percent(interval=CPU_SAMPLE_WINDOW_SECONDS)
