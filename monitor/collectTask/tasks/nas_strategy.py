"""提供 Linux NAS 策略共享的 sysfs 指标采集能力。"""

import glob

from .system_strategy import SystemCollectionStrategy


class LinuxNasCollectionStrategy(SystemCollectionStrategy):
    """为 Linux NAS 策略提供 CPU 频率、温度读取与通用回退。"""

    def cpu_frequency_ghz(self, collector):
        """优先读取 NAS sysfs 实时频率，缺失时回退通用实现。"""
        values = self._read_numeric_files(
            "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq",
            minimum=1,
            maximum=10000000,
        )
        if values:
            return round(sum(values) / len(values) / 1000000, 2)
        return super().cpu_frequency_ghz(collector)

    def cpu_temperature(self, collector):
        """优先读取 NAS sysfs 温度，缺失时回退通用实现。"""
        patterns = (
            "/sys/class/thermal/thermal_zone*/temp",
            "/sys/class/hwmon/hwmon*/temp*_input",
        )
        values = []
        for pattern in patterns:
            values.extend(self._read_numeric_files(pattern, minimum=1000, maximum=150000))
        if values:
            return round(max(values) / 1000, 1)
        return super().cpu_temperature(collector)

    @staticmethod
    def _read_numeric_files(pattern, minimum, maximum):
        """读取匹配路径中的有效数字，忽略无权限或内容异常的节点。"""
        values = []
        for path in glob.glob(pattern):
            try:
                with open(path, "r", encoding="ascii") as value_file:
                    value = float(value_file.read().strip())
            except (OSError, TypeError, ValueError):
                continue
            if minimum <= value <= maximum:
                values.append(value)
        return values
