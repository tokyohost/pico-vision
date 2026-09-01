"""功耗各字段的默认解析策略。"""

from ..base import ContextFieldStrategy, StrategyChain, number


POWER_WATTS = StrategyChain(ContextFieldStrategy("power", "watts", number))
POWER_SOURCE = StrategyChain(ContextFieldStrategy("power", "source", default="sensor_host"))
POWER_SCOPE = StrategyChain(ContextFieldStrategy("power", "scope", default="cpu_gpu"))
