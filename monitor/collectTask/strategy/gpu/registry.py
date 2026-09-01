"""GPU 字段专属策略注册表。"""

from ..base import StrategyChain
from .values import DEFAULT_GPU_STRATEGIES


DEVICE_GPU_STRATEGIES = {
    field: () for field in DEFAULT_GPU_STRATEGIES
}


def create_gpu_strategy_chains():
    """为 GPU 每个字段创建专属策略优先、默认策略兜底的短路链。"""
    return {
        field: StrategyChain(*(DEVICE_GPU_STRATEGIES.get(field, ()) + default_strategies))
        for field, default_strategies in DEFAULT_GPU_STRATEGIES.items()
    }


GPU_FIELDS = create_gpu_strategy_chains()
