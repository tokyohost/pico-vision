"""CPU 各字段的 LibreHardwareMonitor 解析策略。"""

from ..base import ContextFieldStrategy, SensorValueStrategy, StrategyChain, iter_sensors, number


class CpuHardwareFrequencyStrategy(SensorValueStrategy):
    """从 CPU 原始时钟传感器解析平均频率。"""

    def parse(self, raw_data, context):
        """优先平均核心时钟，其次读取核心平均时钟并换算为 GHz。"""
        sensors = list(iter_sensors(raw_data, ("Cpu",), "Clock"))
        for preferred_name in ("Cores (Average)", "CPU Core"):
            values = [
                value for _, sensor, value in sensors
                if preferred_name.casefold() in str(sensor.get("name") or "").casefold()
            ]
            if values:
                return round(sum(values) / len(values) / 1000, 2)
        return None


class CpuHardwareTemperatureStrategy(SensorValueStrategy):
    """复用原有 CPU 硬件节点温度解析规则。"""

    PREFERRED_NAMES = ("CPU Package", "CPU Tctl/Tdie", "Core Max", "CPU")

    def parse(self, raw_data, context):
        """按常见 CPU 温度名称选择原始传感器值。"""
        candidates = list(iter_sensors(raw_data, ("Cpu",), "Temperature"))
        for preferred_name in self.PREFERRED_NAMES:
            for _, sensor, value in candidates:
                if str(sensor.get("name") or "").casefold() == preferred_name.casefold():
                    return value
        return candidates[0][2] if candidates else None


class MainboardCpuTemperatureStrategy(SensorValueStrategy):
    """兼容主板、SuperIO 和嵌入式控制器暴露的 CPU 温度。"""

    HARDWARE_TYPES = ("Motherboard", "SuperIO", "EmbeddedController")
    PREFERRED_NAMES = (
        "CPU Package",
        "CPU (Tctl/Tdie)",
        "CPU Tctl/Tdie",
        "Tctl/Tdie",
        "Tdie",
        "PECI Agent 0",
        "CPU Socket",
        "CPU",
        "CPUTIN",
    )

    def parse(self, raw_data, context):
        """按主板传感器名称优先级返回合理范围内的 CPU 温度。"""
        candidates = list(iter_sensors(raw_data, self.HARDWARE_TYPES, "Temperature"))
        for preferred_name in self.PREFERRED_NAMES:
            for _, sensor, value in candidates:
                name = str(sensor.get("name") or "")
                if preferred_name.casefold() in name.casefold() and -20 <= value <= 150:
                    return value
        return None


DEFAULT_CPU_STRATEGIES = {
    "percent": (ContextFieldStrategy("cpu", "percent", number),),
    "frequency_ghz": (
        ContextFieldStrategy("cpu", "frequency_ghz", number),
        CpuHardwareFrequencyStrategy(),
    ),
    "temperature_c": (
        ContextFieldStrategy("cpu", "temperature_c", number),
        CpuHardwareTemperatureStrategy(),
        MainboardCpuTemperatureStrategy(),
    ),
}
