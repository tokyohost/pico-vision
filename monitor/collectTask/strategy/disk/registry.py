"""磁盘字段专属策略注册表。"""

from ..base import StrategyChain
from .values import DEFAULT_DISK_STRATEGIES


DEVICE_DISK_STRATEGIES = {
    field: () for field in DEFAULT_DISK_STRATEGIES
}


def create_disk_strategy_chains():
    """为磁盘每个字段创建专属策略优先、默认策略兜底的短路链。"""
    return {
        field: StrategyChain(*(DEVICE_DISK_STRATEGIES.get(field, ()) + default_strategies))
        for field, default_strategies in DEFAULT_DISK_STRATEGIES.items()
    }


DISK_FIELDS = create_disk_strategy_chains()
