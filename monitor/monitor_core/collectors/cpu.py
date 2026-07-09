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

"""采集 CPU 频率、温度和 Windows 实时速度指标。"""

import ctypes
import os
import platform

import psutil

from monitor_core.collectors.models import LOGGER
from monitor_core.collectors.windows_pdh import _PdhFormattedValue


class _ProcessorPowerInformation(ctypes.Structure):
    """描述 Windows 返回的单个逻辑处理器实时频率与电源状态。"""

    _fields_ = [
        ("number", ctypes.c_ulong),
        ("max_mhz", ctypes.c_ulong),
        ("current_mhz", ctypes.c_ulong),
        ("mhz_limit", ctypes.c_ulong),
        ("max_idle_state", ctypes.c_ulong),
        ("current_idle_state", ctypes.c_ulong),
    ]

class _WindowsPdhCpuFrequencySampler:
    """通过 Windows PDH 读取接近任务管理器的 CPU 当前速度。"""

    _PDH_DOUBLE = 0x00000200
    _COUNTER_PATHS = (
        ("performance", r"\Processor Information(_Total)\% Processor Performance"),
        ("frequency", r"\Processor Information(_Total)\Processor Frequency"),
    )

    def __init__(self):
        """打开 PDH 查询，并优先使用性能百分比换算当前速度。"""
        if platform.system() != "Windows":
            raise OSError("PDH CPU 频率采样仅支持 Windows")
        self.library = ctypes.WinDLL("pdh.dll")
        self.query = ctypes.c_void_p()
        self.counter = ctypes.c_void_p()
        self.mode = None
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
        """按优先级打开第一个可用 CPU 速度计数器。"""
        for mode, path in self._COUNTER_PATHS:
            query = ctypes.c_void_p()
            counter = ctypes.c_void_p()
            if self.library.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
                continue
            if self.library.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) == 0:
                self.query = query
                self.counter = counter
                self.mode = mode
                self.counter_path = path
                self.library.PdhCollectQueryData(self.query)
                return
            self.library.PdhCloseQuery(query)
        raise OSError("Windows CPU 速度 PDH 计数器不可用")

    def sample(self, base_frequency_mhz=None):
        """读取当前 CPU MHz；性能百分比模式下使用基准频率换算。"""
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
        raw_value = float(value.double_value)
        if self.mode == "frequency":
            return raw_value if raw_value > 0 else None
        if self.mode == "performance" and base_frequency_mhz and base_frequency_mhz > 0:
            return max(0.0, base_frequency_mhz * raw_value / 100.0)
        return None

    def close(self):
        """关闭 PDH 查询句柄。"""
        query = getattr(self, "query", None)
        if query and query.value:
            self.library.PdhCloseQuery(query)
            self.query = ctypes.c_void_p()

class CpuMetricsMixin:
    """为系统采集器提供 CPU 频率和温度采集能力。"""

    _windows_cpu_frequency_sampler = None
    _windows_cpu_frequency_sampler_unavailable = False
    _windows_cpu_frequency_source_logged = False

    @classmethod
    def _close_windows_cpu_frequency_sampler(cls):
        """关闭 Windows CPU 速度 PDH 采样器。"""
        sampler = cls._windows_cpu_frequency_sampler
        if sampler is not None:
            sampler.close()
            cls._windows_cpu_frequency_sampler = None

    @staticmethod
    def _windows_processor_power_information():
        """读取 Windows 处理器电源信息数组，失败时返回空元组。"""
        processor_count = os.cpu_count() or 1
        information = (_ProcessorPowerInformation * processor_count)()
        try:
            library = ctypes.WinDLL("powrprof.dll")
            function = library.CallNtPowerInformation
            function.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
            function.restype = ctypes.c_ulong
            status = function(11, None, 0, ctypes.byref(information), ctypes.sizeof(information))
        except (AttributeError, OSError):
            return ()
        return tuple(information) if status == 0 else ()

    @classmethod
    def _windows_cpu_pdh_frequency_mhz(cls):
        """通过 PDH 读取 Windows CPU 当前速度，失败时返回空值。"""
        if cls._windows_cpu_frequency_sampler_unavailable:
            return None
        try:
            if cls._windows_cpu_frequency_sampler is None:
                cls._windows_cpu_frequency_sampler = _WindowsPdhCpuFrequencySampler()
            base_frequency_mhz = cls._windows_cpu_base_frequency_mhz()
            current_mhz = cls._windows_cpu_frequency_sampler.sample(base_frequency_mhz)
            if current_mhz is not None:
                if not cls._windows_cpu_frequency_source_logged:
                    LOGGER.info(
                        "Windows CPU 速度采样源：PDH 计数器 %s，模式=%s，基准=%.0f MHz，当前=%.0f MHz",
                        cls._windows_cpu_frequency_sampler.counter_path,
                        cls._windows_cpu_frequency_sampler.mode,
                        base_frequency_mhz or 0,
                        current_mhz,
                    )
                    cls._windows_cpu_frequency_source_logged = True
                return current_mhz
            LOGGER.warning("Windows CPU 速度 PDH 计数器返回空值，回退到电源信息接口")
        except (AttributeError, OSError, TypeError, ValueError) as error:
            LOGGER.warning("Windows CPU 速度 PDH 采样不可用，回退到电源信息接口：%s", error)
        sampler = cls._windows_cpu_frequency_sampler
        if sampler is not None:
            sampler.close()
            cls._windows_cpu_frequency_sampler = None
        cls._windows_cpu_frequency_sampler_unavailable = True
        return None

    @classmethod
    def _windows_cpu_base_frequency_mhz(cls):
        """读取 Windows CPU 基准 MHz，用于把性能百分比换算为当前速度。"""
        values = [item.max_mhz for item in cls._windows_processor_power_information() if item.max_mhz > 0]
        return sum(values) / len(values) if values else None

    @classmethod
    def _windows_cpu_power_frequency_mhz(cls):
        """通过 Windows 电源信息接口读取全部逻辑处理器的 MHz 平均值。"""
        if not cls._windows_cpu_frequency_source_logged:
            LOGGER.info("Windows CPU 速度采样源：CallNtPowerInformation 电源信息接口")
            cls._windows_cpu_frequency_source_logged = True
        values = [item.current_mhz for item in cls._windows_processor_power_information() if item.current_mhz > 0]
        return sum(values) / len(values) if values else None

    @classmethod
    def _windows_cpu_current_frequency_mhz(cls):
        """优先通过 PDH 读取接近任务管理器的实时 MHz，失败时回退电源信息接口。"""
        current_mhz = cls._windows_cpu_pdh_frequency_mhz()
        if current_mhz is not None:
            return current_mhz
        return cls._windows_cpu_power_frequency_mhz()

    @classmethod
    def _cpu_frequency_ghz(cls):
        """读取 CPU 各逻辑处理器的实时频率平均值并换算为 GHz。"""
        if platform.system() == "Windows":
            current_mhz = cls._windows_cpu_current_frequency_mhz()
            return round(current_mhz / 1000, 2) if current_mhz is not None else None
        try:
            frequencies = psutil.cpu_freq(percpu=True) or ()
        except (AttributeError, OSError, RuntimeError, TypeError):
            frequencies = ()
        values = [float(item.current) for item in frequencies if getattr(item, "current", 0) > 0]
        if values:
            return round(sum(values) / len(values) / 1000, 2)
        try:
            frequency = psutil.cpu_freq(percpu=False)
        except (AttributeError, OSError, RuntimeError, TypeError):
            return None
        current_mhz = getattr(frequency, "current", None) if frequency is not None else None
        if current_mhz is None or current_mhz <= 0:
            return None
        return round(float(current_mhz) / 1000, 2)

    @staticmethod
    def _cpu_temperature():
        """从系统温度传感器中选择有效的最高 CPU 温度。"""
        try:
            sensors = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        values = [float(item.current) for name in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "soc_thermal") for item in sensors.get(name, ()) if item.current is not None and 0 < float(item.current) < 150]
        return round(max(values), 1) if values else None

