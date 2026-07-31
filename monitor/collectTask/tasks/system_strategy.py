"""定义可注册、可扩展的操作系统采集策略。"""

import platform


class SystemCollectionStrategy:
    """定义不同操作系统采集策略必须实现的统一接口。"""

    priority = 100

    def supports(self, system_name):
        """判断当前策略是否适用于指定操作系统。"""
        raise NotImplementedError

    def create_cpu_percent_sampler(self, logger):
        """创建当前系统对应的 CPU 占用率采样器。"""
        raise NotImplementedError

    def cpu_frequency_ghz(self, collector):
        """读取当前系统 CPU 频率，默认复用通用采集器实现。"""
        return collector._cpu_frequency_ghz()

    def cpu_temperature(self, collector):
        """读取当前系统 CPU 温度，默认复用通用采集器实现。"""
        return collector._cpu_temperature()


class SystemCollectionStrategyRegistry:
    """维护系统采集策略，并按优先级选择首个适用策略。"""

    def __init__(self, strategies=()):
        """初始化策略注册表并注册给定策略。"""
        self._strategies = []
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy):
        """注册策略实例并保持高优先级策略在前。"""
        if not isinstance(strategy, SystemCollectionStrategy):
            raise TypeError("系统采集策略必须继承 SystemCollectionStrategy")
        self._strategies.append(strategy)
        self._strategies.sort(key=lambda item: item.priority, reverse=True)
        return strategy

    def resolve(self, system_name=None):
        """选择首个支持当前系统的策略，没有匹配项时抛出异常。"""
        current_system = platform.system() if system_name is None else system_name
        for strategy in self._strategies:
            if strategy.supports(current_system):
                return strategy
        raise RuntimeError("没有可用于 {} 的系统采集策略".format(current_system))


def create_system_collection_strategy_registry():
    """创建包含各 NAS、桌面系统和通用 Linux 策略的默认注册表。"""
    from .linux.system_strategy import LinuxCollectionStrategy
    from .qnap.system_strategy import QnapCollectionStrategy
    from .synology.system_strategy import SynologyCollectionStrategy
    from .truenas.system_strategy import TrueNasCollectionStrategy
    from .win.system_strategy import WindowsCollectionStrategy

    return SystemCollectionStrategyRegistry((
        SynologyCollectionStrategy(),
        QnapCollectionStrategy(),
        TrueNasCollectionStrategy(),
        WindowsCollectionStrategy(),
        LinuxCollectionStrategy(),
    ))


def resolve_system_collection_strategy(system_name=None):
    """从默认注册表中解析当前操作系统应使用的采集策略。"""
    return create_system_collection_strategy_registry().resolve(system_name)
