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

"""采集系统功耗指标。"""

import platform
import time
from pathlib import Path


class PowerMonitor:
    """通过 Linux RAPL 能耗计数器计算可获得的硬件实时功耗。"""

    def __init__(self):
        """初始化上一组能耗计数器和采样时间。"""
        self.last_counters = None
        self.last_time = None

    @staticmethod
    def _read_integer(path):
        """读取 sysfs 中的整数计数器，读取失败时返回空值。"""
        try:
            return int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _iter_energy_paths(powercap_root):
        """遍历 powercap 目录并跟随 sysfs 区域链接，返回去重后的能耗文件。"""
        directories = [powercap_root]
        visited_directories = set()
        visited_energy_paths = set()
        while directories:
            directory = directories.pop()
            try:
                directory_key = str(directory.resolve())
                children = tuple(directory.iterdir())
            except OSError:
                continue
            if directory_key in visited_directories:
                continue
            visited_directories.add(directory_key)
            for child in children:
                try:
                    if child.name == "energy_uj":
                        energy_key = str(child.resolve())
                        if energy_key not in visited_energy_paths:
                            visited_energy_paths.add(energy_key)
                            yield child.resolve()
                    elif child.is_dir():
                        directories.append(child)
                except OSError:
                    continue

    @classmethod
    def _read_energy_counters(cls):
        """读取顶层 RAPL 区域，避免把子区域功耗重复计入。"""
        if platform.system() != "Linux":
            return {}
        counters = {}
        powercap_root = Path("/sys/class/powercap")
        for energy_path in cls._iter_energy_paths(powercap_root):
            parent_energy = energy_path.parent.parent / "energy_uj"
            if parent_energy.exists():
                continue
            energy = cls._read_integer(energy_path)
            maximum = cls._read_integer(energy_path.parent / "max_energy_range_uj")
            if energy is not None:
                counters[str(energy_path.parent)] = (energy, maximum)
        return counters

    def snapshot(self):
        """返回当前功耗瓦数、采集来源和统计范围。"""
        counters = self._read_energy_counters()
        now = time.monotonic()
        watts = None
        if counters and self.last_counters and self.last_time is not None:
            elapsed = now - self.last_time
            if elapsed > 0 and counters.keys() == self.last_counters.keys():
                energy_delta = 0
                for key, (energy, maximum) in counters.items():
                    previous = self.last_counters[key][0]
                    delta = energy - previous
                    if delta < 0 and maximum:
                        delta += maximum
                    energy_delta += max(0, delta)
                watts = round(energy_delta / 1_000_000 / elapsed, 1)
        self.last_counters = counters or None
        self.last_time = now if counters else None
        return {
            "watts": watts,
            "source": "linux_rapl" if counters else "unavailable",
            "scope": "rapl_packages" if counters else "unavailable",
        }
