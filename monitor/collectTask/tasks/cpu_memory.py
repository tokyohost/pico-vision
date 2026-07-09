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


class _PdhFormattedItem(ctypes.Structure):
    """描述 Windows PDH 通配符实例名称及其格式化值。"""

    _fields_ = [("name", ctypes.c_wchar_p), ("value", _PdhFormattedValue)]


class _WindowsPdhCpuSampler:
    """通过 Windows PDH 读取每个逻辑核心占用率并计算平均值。"""

    _PDH_MORE_DATA = 0x800007D2
    _PDH_DOUBLE = 0x00000200
    _COUNTER_PATHS = (
        r"\Processor Information(*)\% Processor Utility",
        r"\Processor(*)\% Processor Time",
    )

    def __init__(self):
        """初始化 PDH 查询，并优先使用每核心 Processor Utility 计数器。"""
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
        self.library.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
        self.library.PdhGetFormattedCounterArrayW.restype = ctypes.c_ulong
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
        """通过指定阻塞窗口采样每核心占用率，并返回算术平均百分比。"""
        if self.library.PdhCollectQueryData(self.query) != 0:
            return None
        time.sleep(max(0.0, float(sample_window_seconds)))
        if self.library.PdhCollectQueryData(self.query) != 0:
            return None
        buffer_size = ctypes.c_ulong()
        item_count = ctypes.c_ulong()
        status = self.library.PdhGetFormattedCounterArrayW(
            self.counter, self._PDH_DOUBLE,
            ctypes.byref(buffer_size), ctypes.byref(item_count), None,
        )
        if status != self._PDH_MORE_DATA or buffer_size.value == 0:
            return None
        buffer = ctypes.create_string_buffer(buffer_size.value)
        status = self.library.PdhGetFormattedCounterArrayW(
            self.counter, self._PDH_DOUBLE,
            ctypes.byref(buffer_size), ctypes.byref(item_count), buffer,
        )
        if status != 0 or item_count.value == 0:
            return None
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhFormattedItem))
        values = []
        for index in range(item_count.value):
            item = items[index]
            name = str(item.name or "")
            if name.lower() == "_total" or item.value.status != 0:
                continue
            values.append(max(0.0, min(100.0, float(item.value.double_value))))
        return sum(values) / len(values) if values else None

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
        use_sensor_host_cpu = self._sensor_host_available("cpu")
        use_sensor_host_memory = self._sensor_host_available("memory")
        if use_sensor_host_cpu and use_sensor_host_memory:
            return {}
        cpu = None if use_sensor_host_cpu else round(self._cpu_percent(), 1)
        memory = None if use_sensor_host_memory else psutil.virtual_memory()
        now = time.monotonic()
        fragment = {}
        if cpu is not None:
            update_per_second(
                self.collector.histories["cpu"],
                round(cpu, 1),
                self.collector.history_states.setdefault("cpu", {}),
                now,
            )
            fragment["cpu"] = {
                "percent": cpu,
                "frequency_ghz": self.collector._cpu_frequency_ghz(),
                "temperature_c": self.collector._cpu_temperature(),
                "history": list(self.collector.histories["cpu"]),
            }
        if memory is not None:
            update_per_second(
                self.collector.histories["memory"],
                round(memory.percent, 1),
                self.collector.history_states.setdefault("memory", {}),
                now,
            )
            fragment["memory"] = {
                "percent": round(memory.percent, 1),
                "used_bytes": memory.used,
                "total_bytes": memory.total,
                "history": list(self.collector.histories["memory"]),
            }
        if self._sensor_host_available("cpu"):
            fragment.pop("cpu", None)
        if self._sensor_host_available("memory"):
            fragment.pop("memory", None)
        return fragment

    def _sensor_host_available(self, metric_name):
        """判断 SensorHost 是否正在优先提供指定指标。"""
        checker = getattr(self.collector, "is_sensor_host_metric_available", None)
        return bool(checker is not None and checker(metric_name))

    def _cpu_percent(self):
        """Windows 优先读取 PDH CPU 计数器，失败时回退到 psutil 阻塞采样。"""
        if platform.system() == "Windows" and not self._windows_cpu_sampler_unavailable:
            try:
                if self._windows_cpu_sampler is None:
                    self._windows_cpu_sampler = _WindowsPdhCpuSampler()
                    if not self._cpu_percent_source_logged:
                        LOGGER.info(
                            "Windows CPU 利用率采样源：PDH 每核心平均，计数器 %s，采样窗口=%.1f秒",
                            self._windows_cpu_sampler.counter_path,
                            CPU_SAMPLE_WINDOW_SECONDS,
                        )
                        self._cpu_percent_source_logged = True
                value = self._windows_cpu_sampler.sample(CPU_SAMPLE_WINDOW_SECONDS)
                if value is not None:
                    return value
                LOGGER.warning(
                    "Windows CPU 利用率 PDH 每核心计数器返回空值，回退到 psutil 每核心平均(interval=%.1f)",
                    CPU_SAMPLE_WINDOW_SECONDS,
                )
            except (AttributeError, OSError, TypeError, ValueError) as error:
                LOGGER.warning(
                    "Windows CPU 利用率 PDH 每核心采样不可用，回退到 psutil 每核心平均(interval=%.1f)：%s",
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
                "Windows CPU 利用率采样源：psutil 每核心平均(interval=%.1f)",
                CPU_SAMPLE_WINDOW_SECONDS,
            )
            self._cpu_percent_source_logged = True
        return self._psutil_per_core_average()

    @staticmethod
    def _psutil_per_core_average():
        """使用 psutil 读取所有逻辑核心占用率并返回算术平均值。"""
        values = psutil.cpu_percent(interval=CPU_SAMPLE_WINDOW_SECONDS, percpu=True)
        return sum(values) / len(values) if values else 0.0
