"""异步采集 macOS GPU、CPU 频率、温度与功耗，不阻塞任务线程。"""

import json
import os
import platform
import shutil
import threading
import time
from pathlib import Path

import psutil

from .native import number, plist_samples, read_plist, run_command


SAMPLE_TTL_SECONDS = 8.0
MAX_SAMPLE_FILE_BYTES = 4 * 1024 * 1024


def empty_sample(reason="等待 macOS 原生采样"):
    """创建完整的空指标，避免把不可用传感器误报为零。"""
    return {
        "frequency_ghz": None, "frequency_source": "unavailable", "cpu_temperature_c": None,
        "temperature_source": "unavailable",
        "gpu": {"percent": None, "temperature_c": None, "dedicated_memory_used_bytes": None,
                "dedicated_memory_total_bytes": None, "source": "unavailable", "reason": reason,
                "temperature_source": "unavailable"},
        "power": {"watts": None, "source": "unavailable", "scope": "unavailable", "reason": reason},
    }


def parse_powermetrics(payload):
    """规范化 Intel 与 Apple Silicon plist；能量除以真实采样周期后换算瓦数。"""
    sample = empty_sample("powermetrics 未提供此硬件指标")
    processor = payload.get("processor", {})
    if not isinstance(processor, dict):
        processor = {}
    frequency = number(processor.get("freq_hz"), maximum=100e9)
    if frequency is None:
        # Apple Silicon 各簇频率按逻辑核心数量加权，不能直接求簇频率之和。
        clusters = processor.get("clusters", [])
        weighted = []
        for cluster in clusters if isinstance(clusters, list) else []:
            if not isinstance(cluster, dict):
                continue
            hz = number(cluster.get("freq_hz"), maximum=100e9)
            cores = cluster.get("cpus", [])
            count = len(cores) if isinstance(cores, list) and cores else 1
            if hz is not None:
                weighted.append((hz, count))
        if weighted:
            frequency = sum(hz * count for hz, count in weighted) / sum(count for _, count in weighted)
    if frequency is not None and frequency > 0:
        sample.update(frequency_ghz=round(frequency / 1e9, 3), frequency_source="powermetrics")

    gpu = payload.get("gpu", payload.get("GPU", {}))
    if isinstance(gpu, list):
        gpu = gpu[0] if gpu else {}
    if not isinstance(gpu, dict):
        gpu = {}
    active = number(gpu.get("active_ratio"), maximum=1)
    idle = number(gpu.get("idle_ratio", gpu.get("c_state_ratio")), maximum=1)
    if active is None and idle is not None:
        active = 1 - idle
    if active is not None:
        sample["gpu"].update(percent=round(active * 100, 1), source="powermetrics", reason="")

    smc = payload.get("smc", {})
    if isinstance(smc, dict):
        temperature = number(smc.get("cpu_die_temperature"), minimum=1, maximum=150)
        gpu_temperature = number(smc.get("gpu_die_temperature"), minimum=1, maximum=150)
        if temperature is not None:
            sample.update(cpu_temperature_c=round(temperature, 1), temperature_source="powermetrics_smc")
        if gpu_temperature is not None:
            sample["gpu"].update(temperature_c=round(gpu_temperature, 1), source="powermetrics",
                                 temperature_source="powermetrics_smc", reason="")

    watts = number(processor.get("combined_power"))
    scope = "soc_cpu_gpu_ane"
    if watts is not None:
        watts /= 1000  # Apple Silicon 的 *_power 字段单位为毫瓦。
    else:
        elapsed_ns = number(payload.get("elapsed_ns"), minimum=1)
        joules = number(processor.get("package_joules"))
        if joules is not None and elapsed_ns is not None:
            watts = joules * 1e9 / elapsed_ns
            scope = "cpu_package"
        else:
            components = [number(processor.get(key)) for key in ("cpu_power", "gpu_power", "ane_power")]
            if all(value is not None for value in components):
                watts = sum(components) / 1000
            elif elapsed_ns is not None:
                energies = [number(processor.get(key)) for key in ("cpu_energy", "gpu_energy", "ane_energy")]
                if all(value is not None for value in energies):
                    watts = sum(energies) * 1e6 / elapsed_ns  # *_energy 为毫焦耳。
    if watts is None:
        cpu_power = number(processor.get("cpu_power"))
        if cpu_power is not None:
            watts, scope = cpu_power / 1000, "cpu_only"
    watts = number(watts, maximum=100000)
    if watts is not None:
        sample["power"] = {"watts": round(watts, 2), "source": "powermetrics", "scope": scope, "reason": ""}
    return sample


def parse_ioreg_gpu(payload):
    """读取 IOAccelerator 利用率与独立显存，不把统一内存当作独立显存。"""
    candidates = []
    pending = list(payload) if isinstance(payload, list) else [payload]
    while pending:
        device = pending.pop()
        if not isinstance(device, dict):
            continue
        pending.extend(device.get("IORegistryEntryChildren", []) or [])
        stats = device.get("PerformanceStatistics", {})
        if not isinstance(stats, dict):
            continue
        percent = number(stats.get("Device Utilization %", stats.get("GPU Activity(%)")), maximum=100)
        total = number(device.get("VRAM,totalMB"))
        used = number(stats.get("vramUsedBytes"))
        if percent is not None or used is not None:
            candidates.append({"percent": percent, "temperature_c": None,
                               "dedicated_memory_used_bytes": int(used) if used is not None and total else None,
                               "dedicated_memory_total_bytes": int(total * 1024 * 1024) if total else None,
                               "source": "iokit_ioaccelerator", "reason": ""})
    # 与当前协议单 GPU 字段一致，选择负载最高的设备而非叠加百分比。
    return max(candidates, key=lambda item: item["percent"] or 0) if candidates else None


def parse_battery_power(payload):
    """仅把放电电流与电压换算为电池侧功耗，排除充电器额定功率。"""
    for battery in payload if isinstance(payload, list) else []:
        if not isinstance(battery, dict) or battery.get("ExternalConnected") is not False:
            continue
        current = battery.get("InstantAmperage", battery.get("Amperage"))
        voltage = number(battery.get("Voltage"), minimum=1)
        if isinstance(current, int) and current >= 2 ** 63:
            current -= 2 ** 64  # IOKit 可能用无符号 64 位整数表示负电流。
        current = number(current, minimum=-100000, maximum=100000)
        if current is not None and current <= 0 and voltage is not None:
            return {"watts": round(-current * voltage / 1e6, 2), "source": "iokit_battery",
                    "scope": "battery_discharge", "reason": ""}
    return None


def parse_macmon(payload):
    """读取 macmon JSON 中的活动比例、SMC 温度和真实瓦数。"""
    sample = empty_sample("macmon 未提供此指标，请检查版本与硬件支持")
    temperatures = payload.get("temp", {})
    if isinstance(temperatures, dict):
        cpu = number(temperatures.get("cpu_temp_avg"), minimum=1, maximum=150)
        gpu = number(temperatures.get("gpu_temp_avg"), minimum=1, maximum=150)
        if cpu is not None:
            sample.update(cpu_temperature_c=round(cpu, 1), temperature_source="macmon_smc")
        if gpu is not None:
            sample["gpu"].update(temperature_c=round(gpu, 1), source="macmon_smc",
                                 temperature_source="macmon_smc", reason="")
    ratio = number(payload.get("gpu_active_ratio"), maximum=1)
    if ratio is not None:
        sample["gpu"].update(percent=round(ratio * 100, 1), source="macmon_ioreport_active", reason="")
    else:
        usage = payload.get("gpu_usage")
        ratio = number(usage[1], maximum=1) if isinstance(usage, (list, tuple)) and len(usage) == 2 else None
        if ratio is not None:
            sample["gpu"].update(percent=round(ratio * 100, 1), source="macmon_ioreport_scaled",
                                 reason="旧版 macmon 返回频率缩放负载比例，不是活动驻留比例")
    cores = []
    for key in ("ecpu_cores", "pcpu_cores"):
        values = payload.get(key, [])
        for core in values if isinstance(values, list) else []:
            if isinstance(core, dict):
                mhz = number(core.get("freq_mhz"), minimum=1)
                if mhz is not None:
                    cores.append(mhz)
    if not cores:
        for key in ("ecpu_core_usages", "pcpu_core_usages"):
            values = payload.get(key, [])
            for core in values if isinstance(values, list) else []:
                mhz = number(core[0], minimum=1) if isinstance(core, (list, tuple)) and len(core) == 2 else None
                if mhz is not None:
                    cores.append(mhz)
    if cores:
        sample.update(frequency_ghz=round(sum(cores) / len(cores) / 1000, 3), frequency_source="macmon_ioreport")
    watts = number(payload.get("sys_power"), minimum=0.001, maximum=100000)
    scope = "system"
    if watts is None:
        components = [number(payload.get(key)) for key in ("cpu_power", "gpu_power", "ane_power")]
        if all(value is not None for value in components):
            watts, scope = number(sum(components), minimum=0.001, maximum=100000), "soc_cpu_gpu_ane"
    if watts is not None:
        sample["power"] = {"watts": round(watts, 2), "source": "macmon_ioreport", "scope": scope,
                           "reason": "私有硬件计数器的支持范围由 macmon 版本决定"}
    return sample


class MacOsTelemetry:
    """共享一条可停止的原生采样线程，发布带过期保护的原子快照。"""

    def __init__(self, interval=2.0):
        """初始化采样状态及可选的外置特权 powermetrics 样本路径。"""
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._result = (empty_sample(), 0, 0.0)
        self._samplers = None
        self._power_retry_at = 0.0
        self.sample_file = os.environ.get("MONITOR_MAC_POWERMETRICS_FILE", "").strip()
        self._sample_file_signature = None
        self._file_sample = None
        self._file_sample_time = 0.0
        self._nominal_frequency = None
        self._macmon_path = None
        self._macmon_retry_at = 0.0

    def start(self):
        """仅启动一次后台线程，避免在任务发现阶段运行 macOS 命令。"""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="macOS 原生指标采集", daemon=True)
            self._thread.start()

    def close(self):
        """停止采样并有界等待线程退出；命令超时保证不会永久阻塞。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=7)

    def snapshot(self):
        """复制最近有效样本，过期时清除实时数据而不是持续发送旧值。"""
        sample, version, sampled_at = self._result
        if not sampled_at or time.monotonic() - sampled_at > SAMPLE_TTL_SECONDS:
            sample = empty_sample("macOS 样本尚未就绪或已过期")
        return dict(sample, gpu=dict(sample["gpu"]), power=dict(sample["power"])), version

    def cpu_frequency(self):
        """优先返回实时簇频率，Intel 降级频率明确标记为标称值。"""
        sample, _ = self.snapshot()
        if sample["frequency_ghz"] is not None:
            return sample["frequency_ghz"], sample["frequency_source"]
        try:
            frequency = psutil.cpu_freq()
            value = number(frequency.current if frequency else None, minimum=1)
        except (AttributeError, OSError, RuntimeError, NotImplementedError):
            value = None
        if value is not None:
            return round(value / 1000, 3), "psutil_nominal"
        return self._nominal_frequency, "sysctl_nominal" if self._nominal_frequency else "unavailable"

    def _read_power_sample(self):
        """读取外置样本或直接执行已具备权限的 powermetrics，绝不主动提权。"""
        if self.sample_file:
            try:
                path = Path(self.sample_file)
                stat = path.stat()
                if stat.st_size > MAX_SAMPLE_FILE_BYTES or time.time() - stat.st_mtime > SAMPLE_TTL_SECONDS:
                    return None
                signature = (stat.st_mtime_ns, stat.st_size)
                if signature != self._sample_file_signature:
                    with path.open("rb") as stream:
                        samples = plist_samples(stream.read(MAX_SAMPLE_FILE_BYTES + 1))
                    self._sample_file_signature = signature
                    self._file_sample = samples[-1] if samples else None
                    self._file_sample_time = time.monotonic()
                if time.monotonic() - self._file_sample_time <= SAMPLE_TTL_SECONDS:
                    return self._file_sample
            except (OSError, ValueError):
                pass
            return None
        if getattr(os, "geteuid", lambda: -1)() != 0 or time.monotonic() < self._power_retry_at:
            return None
        if self._samplers is None:
            help_result = run_command(["/usr/bin/powermetrics", "--help"])
            help_text = (help_result.stdout + help_result.stderr).decode("utf-8", "replace") if help_result else ""
            self._samplers = [name for name in ("cpu_power", "gpu_power", "smc") if name in help_text]
        if self._stop.is_set():
            return None
        command = ["/usr/bin/powermetrics", "-n", "1", "-i", "1000", "-f", "plist"]
        if self._samplers:
            command.extend(["--samplers", ",".join(self._samplers)])
        result = run_command(command)
        samples = plist_samples(result.stdout) if result is not None and result.returncode == 0 else []
        if not samples:
            self._power_retry_at = time.monotonic() + 30
        return samples[-1] if samples else None

    def _sample(self):
        """合并特权功耗与普通用户 IOKit 数据，并保留各指标真实统计范围。"""
        payload = self._read_power_sample()
        sample = parse_powermetrics(payload) if payload else empty_sample("功耗与温度需要 powermetrics 权限或外置样本")
        if self._stop.is_set():
            return sample
        if self._macmon_path and time.monotonic() >= self._macmon_retry_at:
            result = run_command([self._macmon_path, "pipe", "-s", "1", "-i", "1000"])
            macmon = None
            if result is not None and result.returncode == 0:
                try:
                    macmon = json.loads(result.stdout)
                except (ValueError, UnicodeError):
                    pass
            if isinstance(macmon, dict):
                native = parse_macmon(macmon)
                # powermetrics 已有的值优先保留，macmon 补齐普通用户可读取的温度等字段。
                for key in ("frequency_ghz", "cpu_temperature_c"):
                    if sample[key] is None and native[key] is not None:
                        sample[key] = native[key]
                        source_key = "frequency_source" if key == "frequency_ghz" else "temperature_source"
                        sample[source_key] = native[source_key]
                if sample["gpu"]["percent"] is None and native["gpu"]["percent"] is not None:
                    sample["gpu"].update(percent=native["gpu"]["percent"], source=native["gpu"]["source"],
                                         reason=native["gpu"]["reason"])
                if sample["gpu"]["temperature_c"] is None:
                    sample["gpu"]["temperature_c"] = native["gpu"]["temperature_c"]
                    sample["gpu"]["temperature_source"] = native["gpu"]["temperature_source"]
                    if native["gpu"]["temperature_c"] is not None and sample["gpu"]["source"] == "unavailable":
                        sample["gpu"].update(source="macmon_smc", reason="GPU 温度可用，GPU 负载尚不可用")
                if sample["power"]["watts"] is None and native["power"]["watts"] is not None:
                    sample["power"] = native["power"]
            else:
                self._macmon_retry_at = time.monotonic() + 30
        if self._stop.is_set():
            return sample
        gpu = parse_ioreg_gpu(read_plist(["/usr/sbin/ioreg", "-r", "-c", "IOAccelerator", "-a"], timeout=1))
        if gpu:
            if sample["gpu"]["percent"] is None:
                sample["gpu"].update(percent=gpu["percent"], source=gpu["source"], reason="")
            for key in ("dedicated_memory_used_bytes", "dedicated_memory_total_bytes"):
                sample["gpu"][key] = gpu[key]
        if self._stop.is_set():
            return sample
        if sample["power"]["watts"] is None:
            battery = parse_battery_power(read_plist(["/usr/sbin/ioreg", "-r", "-c", "AppleSmartBattery", "-a"], timeout=1))
            if battery:
                sample["power"] = battery
        return sample

    def _run(self):
        """定时发布新样本，任何原生采样异常均只影响本轮高级指标。"""
        if platform.machine().lower() in ("arm64", "aarch64"):
            configured = os.environ.get("MONITOR_MAC_MACMON_PATH", "").strip()
            candidates = (configured, shutil.which("macmon"), "/opt/homebrew/bin/macmon", "/usr/local/bin/macmon")
            self._macmon_path = next((path for path in candidates if path and os.path.isfile(path) and os.access(path, os.X_OK)), None)
        nominal = run_command(["/usr/sbin/sysctl", "-n", "hw.cpufrequency"], timeout=1)
        hz = number(nominal.stdout.strip()) if nominal and nominal.returncode == 0 else None
        self._nominal_frequency = round(hz / 1e9, 3) if hz and hz > 0 else None
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                sample = self._sample()
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                sample = empty_sample("macOS 原生工具输出不可解析")
            self._result = (sample, self._result[1] + 1, time.monotonic())
            self._stop.wait(max(0.05, self.interval - (time.monotonic() - started)))
