"""传感器值解析策略的基础设施。"""

from abc import ABC, abstractmethod


class SensorValueStrategy(ABC):
    """定义只依赖原始数据和解析上下文的纯解析策略。"""

    @abstractmethod
    def parse(self, raw_data, context):
        """解析一个值；无法解析时返回空值。"""


class StrategyChain:
    """按注册顺序执行策略，并在首个非空结果处立即返回。"""

    def __init__(self, *strategies):
        """保存有序策略，顺序同时代表解析优先级。"""
        self._strategies = tuple(strategies)

    def parse(self, raw_data, context):
        """返回首个有效解析结果，确保后续策略不会再执行。"""
        for strategy in self._strategies:
            value = strategy.parse(raw_data, context)
            if value is not None:
                return value
        return None


class ContextFieldStrategy(SensorValueStrategy):
    """从上下文的指定数据片段读取现有兼容字段。"""

    def __init__(self, section, field, converter=None, default=None):
        """配置上下文片段、字段名和可选转换函数。"""
        self._section = section
        self._field = field
        self._converter = converter
        self._default = default

    def parse(self, raw_data, context):
        """读取现有字段；该实现是旧解析方式的默认策略。"""
        section_data = context.get(self._section) or {}
        value = section_data.get(self._field, self._default)
        return self._converter(value) if self._converter is not None else value


def number(value):
    """把输入转换为有限浮点数，失败时返回空值。"""
    try:
        result = float(value) if value is not None else None
        if result is None or result != result or result in (float("inf"), float("-inf")):
            return None
        return round(result, 2)
    except (TypeError, ValueError, OverflowError):
        return None


def integer(value):
    """把输入转换为整数，失败时返回空值。"""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def clean_text(value):
    """清理硬件名称中的空字符和首尾空白。"""
    return str(value or "").replace("\x00", "").strip()


def iter_sensors(raw_data, hardware_types=None, sensor_type=None):
    """遍历符合硬件类型和传感器类型限制的原始传感器。"""
    allowed_hardware_types = {str(item).casefold() for item in hardware_types or ()}
    expected_sensor_type = str(sensor_type or "").casefold()
    for hardware in raw_data or ():
        hardware_type = str(hardware.get("type") or "")
        if allowed_hardware_types and hardware_type.casefold() not in allowed_hardware_types:
            continue
        for sensor in hardware.get("sensors") or ():
            if expected_sensor_type and str(sensor.get("type") or "").casefold() != expected_sensor_type:
                continue
            value = number(sensor.get("value"))
            if value is not None:
                yield hardware, sensor, value
