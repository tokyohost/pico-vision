"""CPU 字段专属策略注册表。"""

from ..base import StrategyChain
from .values import DEFAULT_CPU_STRATEGIES


DEVICE_CPU_STRATEGIES = {
    "percent": (),
    "frequency_ghz": (),
    "temperature_c": (),
}


def create_cpu_strategy_chains():
    """为 CPU 每个字段创建专属策略优先、默认策略兜底的短路链。"""
    return {
        field: StrategyChain(*(DEVICE_CPU_STRATEGIES.get(field, ()) + default_strategies))
        for field, default_strategies in DEFAULT_CPU_STRATEGIES.items()
    }


CPU_FIELDS = create_cpu_strategy_chains()
