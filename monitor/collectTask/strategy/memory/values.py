"""内存各字段的默认解析策略。"""

from ..base import ContextFieldStrategy, StrategyChain, integer, number


MEMORY_PERCENT = StrategyChain(ContextFieldStrategy("memory", "percent", number))
MEMORY_USED_BYTES = StrategyChain(ContextFieldStrategy("memory", "used_bytes", integer))
MEMORY_AVAILABLE_BYTES = StrategyChain(ContextFieldStrategy("memory", "available_bytes", integer))
