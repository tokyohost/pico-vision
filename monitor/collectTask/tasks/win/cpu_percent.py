"""Windows CPU 占用率采样实现。"""

import ctypes
import time

import psutil


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


class CpuPercentSampler:
    """Windows 优先使用 PDH 采样，失败时回退到 psutil 每核心平均值。"""

    def __init__(self, logger):
        """初始化采样状态，并延迟创建 PDH 采样器。"""
        self.logger = logger
        self._pdh_sampler = None
        self._pdh_unavailable = False
        self._source_logged = False

    def sample(self, sample_window_seconds):
        """读取 CPU 占用率，优先返回 Windows PDH 每核心平均值。"""
        if not self._pdh_unavailable:
            try:
                if self._pdh_sampler is None:
                    self._pdh_sampler = _WindowsPdhCpuSampler()
                    self._log_pdh_source(sample_window_seconds)
                value = self._pdh_sampler.sample(sample_window_seconds)
                if value is not None:
                    return value
                self.logger.warning(
                    "Windows CPU 利用率 PDH 每核心计数器返回空值，回退到 psutil 每核心平均(interval=%.1f)",
                    sample_window_seconds,
                )
            except (AttributeError, OSError, TypeError, ValueError) as error:
                self.logger.warning(
                    "Windows CPU 利用率 PDH 每核心采样不可用，回退到 psutil 每核心平均(interval=%.1f)：%s",
                    sample_window_seconds,
                    error,
                )
            self._close_pdh_sampler()
            self._pdh_unavailable = True
        self._log_psutil_source(sample_window_seconds)
        return self._psutil_per_core_average(sample_window_seconds)

    def _log_pdh_source(self, sample_window_seconds):
        """记录当前正在使用 Windows PDH 采样源。"""
        if not self._source_logged:
            self.logger.info(
                "Windows CPU 利用率采样源：PDH 每核心平均，计数器 %s，采样窗口=%.1f秒",
                self._pdh_sampler.counter_path,
                sample_window_seconds,
            )
            self._source_logged = True

    def _log_psutil_source(self, sample_window_seconds):
        """记录当前正在使用 psutil 采样源。"""
        if not self._source_logged:
            self.logger.info(
                "Windows CPU 利用率采样源：psutil 每核心平均(interval=%.1f)",
                sample_window_seconds,
            )
            self._source_logged = True

    def _close_pdh_sampler(self):
        """关闭当前 PDH 采样器并清理引用。"""
        if self._pdh_sampler is not None:
            self._pdh_sampler.close()
            self._pdh_sampler = None

    @staticmethod
    def _psutil_per_core_average(sample_window_seconds):
        """使用 psutil 读取所有逻辑核心占用率并返回算术平均值。"""
        values = psutil.cpu_percent(interval=sample_window_seconds, percpu=True)
        return sum(values) / len(values) if values else 0.0
