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

"""采集 NVIDIA、Windows PDH 和 Linux sysfs GPU 指标。"""

import ctypes
import os
import platform
import threading
import time
from pathlib import Path

from monitor_core.collectors.windows_pdh import _PdhFormattedItem


class _NvmlUtilization(ctypes.Structure):
    """描述 NVML 返回的 GPU 核心与显存控制器使用率。"""

    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

class _NvmlMemory(ctypes.Structure):
    """描述 NVML 返回的 GPU 专用显存容量。"""

    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]

class _NvmlGpuBackend:
    """通过进程内常驻 NVML 接口采集 NVIDIA GPU 使用率。"""

    def __init__(self):
        """加载 NVML 动态库、初始化接口并缓存全部设备句柄。"""
        self.library = self._load_library()
        self._configure_functions()
        if self.library.nvmlInit_v2() != 0:
            raise OSError("NVML 初始化失败")
        count = ctypes.c_uint()
        if self.library.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
            self.close()
            raise OSError("NVML 无法枚举 GPU")
        self.devices = []
        for index in range(count.value):
            handle = ctypes.c_void_p()
            if self.library.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) == 0:
                self.devices.append(handle)
        if not self.devices:
            self.close()
            raise OSError("未发现 NVIDIA GPU")

    @staticmethod
    def _load_library():
        """按操作系统常见安装位置加载 NVML 动态库。"""
        candidates = ["nvml.dll"] if platform.system() == "Windows" else ["libnvidia-ml.so.1", "libnvidia-ml.so"]
        if platform.system() == "Windows":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            program_files = os.environ.get("ProgramW6432", r"C:\Program Files")
            candidates = [
                os.path.join(system_root, "System32", "nvml.dll"),
                os.path.join(program_files, "NVIDIA Corporation", "NVSMI", "nvml.dll"),
                *candidates,
            ]
        last_error = None
        for candidate in candidates:
            try:
                loader = ctypes.WinDLL if platform.system() == "Windows" else ctypes.CDLL
                return loader(candidate)
            except OSError as error:
                last_error = error
        raise OSError("未找到 NVML 动态库") from last_error

    def _configure_functions(self):
        """声明当前使用的 NVML 函数参数与返回类型。"""
        self.library.nvmlInit_v2.restype = ctypes.c_int
        self.library.nvmlShutdown.restype = ctypes.c_int
        self.library.nvmlDeviceGetCount_v2.argtypes = [ctypes.POINTER(ctypes.c_uint)]
        self.library.nvmlDeviceGetCount_v2.restype = ctypes.c_int
        self.library.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        self.library.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
        self.library.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlUtilization)]
        self.library.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
        self.library.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
        self.library.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
        self.library.nvmlDeviceGetTemperature.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint)]
        self.library.nvmlDeviceGetTemperature.restype = ctypes.c_int

    def sample(self):
        """返回全部 NVIDIA GPU 的使用率、专用显存与最高温度。"""
        percentages = []
        used_bytes = 0
        total_bytes = 0
        temperatures = []
        for device in self.devices:
            utilization = _NvmlUtilization()
            if self.library.nvmlDeviceGetUtilizationRates(device, ctypes.byref(utilization)) == 0:
                percentages.append(utilization.gpu)
            memory = _NvmlMemory()
            if self.library.nvmlDeviceGetMemoryInfo(device, ctypes.byref(memory)) == 0:
                used_bytes += memory.used
                total_bytes += memory.total
            temperature = ctypes.c_uint()
            if self.library.nvmlDeviceGetTemperature(device, 0, ctypes.byref(temperature)) == 0:
                temperatures.append(temperature.value)
        return {
            "percent": max(percentages) if percentages else None,
            "dedicated_memory_used_bytes": used_bytes if total_bytes else None,
            "dedicated_memory_total_bytes": total_bytes or None,
            "temperature_c": max(temperatures) if temperatures else None,
        }

    def close(self):
        """关闭已经初始化的 NVML 会话。"""
        library = getattr(self, "library", None)
        if library is not None:
            try:
                library.nvmlShutdown()
            except (AttributeError, OSError):
                pass

class _WindowsPdhGpuBackend:
    """通过常驻 Windows PDH 查询采集任意厂商 GPU 使用率。"""

    _PDH_MORE_DATA = 0x800007D2
    _PDH_DOUBLE = 0x00000200

    def __init__(self):
        """打开 PDH 查询并添加语言无关的 GPU Engine 通配符计数器。"""
        if platform.system() != "Windows":
            raise OSError("PDH 仅支持 Windows")
        self.library = ctypes.WinDLL("pdh.dll")
        self.query = ctypes.c_void_p()
        self.counter = ctypes.c_void_p()
        self._configure_functions()
        if self.library.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("PDH 查询初始化失败")
        path = r"\GPU Engine(*engtype_3D)\Utilization Percentage"
        if self.library.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(self.counter)) != 0:
            self.close()
            raise OSError("GPU Engine 计数器不可用")
        self.library.PdhCollectQueryData(self.query)

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

    def sample(self):
        """采集一次 PDH 数据并返回所有 3D 引擎中的最高使用率。"""
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
        values = [items[index].value.double_value for index in range(item_count.value) if items[index].value.status == 0]
        return {
            "percent": max(values) if values else None,
            "dedicated_memory_used_bytes": None,
            "dedicated_memory_total_bytes": None,
            "temperature_c": None,
        }

    def close(self):
        """关闭 PDH 查询句柄。"""
        query = getattr(self, "query", None)
        if query and query.value:
            self.library.PdhCloseQuery(query)
            self.query = ctypes.c_void_p()

class _LinuxSysfsGpuBackend:
    """通过 Linux DRM sysfs 低开销采集 AMD GPU 使用率。"""

    def __init__(self):
        """缓存所有可读取的 GPU 忙碌百分比文件路径。"""
        self.devices = tuple(
            path for path in Path("/sys/class/drm").glob("card*/device")
            if (path / "gpu_busy_percent").is_file()
        )
        if not self.devices:
            raise OSError("未发现可用 GPU sysfs 指标")

    def sample(self):
        """返回全部 sysfs GPU 的使用率、专用显存与最高温度。"""
        percentages = []
        used_bytes = 0
        total_bytes = 0
        temperatures = []
        for device in self.devices:
            try:
                percentages.append(float((device / "gpu_busy_percent").read_text(encoding="ascii").strip()))
            except (OSError, ValueError):
                pass
            try:
                total = int((device / "mem_info_vram_total").read_text(encoding="ascii").strip())
                used = int((device / "mem_info_vram_used").read_text(encoding="ascii").strip())
                total_bytes += total
                used_bytes += used
            except (OSError, ValueError):
                pass
            for path in device.glob("hwmon/hwmon*/temp*_input"):
                try:
                    value = float(path.read_text(encoding="ascii").strip()) / 1000
                except (OSError, ValueError):
                    continue
                if 0 < value < 150:
                    temperatures.append(value)
        return {
            "percent": max(percentages) if percentages else None,
            "dedicated_memory_used_bytes": used_bytes if total_bytes else None,
            "dedicated_memory_total_bytes": total_bytes or None,
            "temperature_c": max(temperatures) if temperatures else None,
        }

    def close(self):
        """兼容统一后端关闭接口，sysfs 无需释放资源。"""

class GpuMonitor:
    """使用常驻原生接口每秒采集 GPU，主循环仅从内存读取快照。"""

    def __init__(self, interval=1.0, unavailable_interval=300.0):
        """初始化采样周期、无设备退避周期和可原子替换的结果。"""
        self.interval = interval
        self.unavailable_interval = unavailable_interval
        self._result = (None, 0)
        self.backend = None

    def start(self):
        """启动 GPU 使用率后台采集线程。"""
        threading.Thread(target=self._run, name="GPU 使用率采集", daemon=True).start()

    def snapshot(self):
        """无锁返回最近 GPU 使用率及采样版本。"""
        return self._result

    @staticmethod
    def _create_backend():
        """依次创建 NVIDIA 专用后端和当前系统的通用低开销后端。"""
        backend_types = [_NvmlGpuBackend]
        if platform.system() == "Windows":
            backend_types.append(_WindowsPdhGpuBackend)
        elif platform.system() == "Linux":
            backend_types.append(_LinuxSysfsGpuBackend)
        for backend_type in backend_types:
            try:
                return backend_type()
            except (AttributeError, OSError):
                continue
        return None

    def _run(self):
        """保持原生后端常驻，并按一秒周期发布 GPU 使用率。"""
        while True:
            if self.backend is None:
                self.backend = self._create_backend()
                if self.backend is None:
                    time.sleep(self.unavailable_interval)
                    continue
            started = time.monotonic()
            try:
                value = self.backend.sample()
            except (AttributeError, OSError, ValueError):
                self.backend.close()
                self.backend = None
                value = None
            if value is not None and any(item is not None for item in value.values()):
                if value.get("percent") is not None:
                    value["percent"] = round(max(0, min(100, float(value["percent"]))), 1)
                if value.get("temperature_c") is not None:
                    value["temperature_c"] = round(float(value["temperature_c"]), 1)
                self._result = (value, self._result[1] + 1)
            time.sleep(max(0.05, self.interval - (time.monotonic() - started)))

