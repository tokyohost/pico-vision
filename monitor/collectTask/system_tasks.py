"""定义系统指标采集任务的基类、回调任务和自动发现入口。"""

import importlib
import logging
import pkgutil

from . import tasks as task_package


LOGGER = logging.getLogger("pico-monitor.collector")


class CollectionTask:
    """定义采集子任务的运行状态、默认频率和统一执行接口。"""

    name = "unnamed"
    zh_name = "未命名采集任务"
    default_interval = 1.0
    order = 100

    def __init__(self, collector):
        """保存系统采集器，并初始化调度状态。"""
        self.collector = collector
        self.scheduled = False
        self.interval = float(self.default_interval)
        self.next_run_time = 0.0

    def configure_interval(self, interval):
        """应用外部配置的采集频率，并保证频率始终为正数。"""
        interval = float(interval)
        if interval <= 0:
            raise ValueError("采集频率必须大于 0")
        self.interval = interval

    def is_due(self, now):
        """判断任务当前是否已经到达下一次可提交时间。"""
        return not self.scheduled and now >= self.next_run_time

    def mark_scheduled(self, now):
        """记录任务已提交，并预定下一次采集时间。"""
        self.scheduled = True
        self.next_run_time = now + self.interval

    def mark_finished(self):
        """记录任务已经结束，允许后续到期时再次提交。"""
        self.scheduled = False

    def collect(self):
        """采集并返回需要合并到完整快照的顶层字段。"""
        raise NotImplementedError


class CallbackCollectionTask(CollectionTask):
    """把 Monitor 提供的附加采集函数封装为标准采集子任务。"""

    order = 1000

    def __init__(self, collector, callback, name, default_interval=1.0, zh_name=None):
        """保存附加采集函数、任务标识、中文名称和默认采集频率。"""
        super().__init__(collector)
        self.callback = callback
        self.name = name
        self.zh_name = zh_name or name
        self.default_interval = float(default_interval)
        self.interval = float(default_interval)

    def collect(self):
        """调用附加采集函数并返回顶层快照片段。"""
        return self.callback()


def _import_task_modules():
    """导入 tasks 包内的全部任务模块，使 CollectionTask 子类完成注册。"""
    prefix = task_package.__name__ + "."
    for module in pkgutil.iter_modules(task_package.__path__, prefix):
        importlib.import_module(module.name)


def _all_task_classes(base_class):
    """递归获取指定基类的全部直接和间接子类。"""
    classes = []
    for subclass in base_class.__subclasses__():
        classes.append(subclass)
        classes.extend(_all_task_classes(subclass))
    return classes


def system_task_classes():
    """扫描 tasks 目录并返回全部系统采集任务类。"""
    _import_task_modules()
    classes = [
        task_class
        for task_class in _all_task_classes(CollectionTask)
        if task_class is not CollectionTask and task_class is not CallbackCollectionTask
    ]
    return tuple(sorted(classes, key=lambda item: (getattr(item, "order", 100), item.__name__)))


def system_task_defaults():
    """返回英文任务标识到默认采集频率的映射，供命令行、托盘和 Linux 配置展示。"""
    return {
        task_class.name: float(getattr(task_class, "default_interval", 1.0))
        for task_class in system_task_classes()
    }


def system_task_zh_names():
    """返回英文任务标识到中文任务名称的映射，供界面展示和旧配置迁移。"""
    return {
        task_class.name: getattr(task_class, "zh_name", task_class.name)
        for task_class in system_task_classes()
    }


def system_task_aliases():
    """返回旧中文任务名称到英文任务标识的映射，兼容历史配置。"""
    aliases = {}
    for name, zh_name in system_task_zh_names().items():
        aliases[zh_name] = name
    return aliases


def create_system_tasks(collector):
    """按稳定顺序创建当前完整系统快照所需的全部采集子任务。"""
    tasks = tuple(task_class(collector) for task_class in system_task_classes())
    LOGGER.info(
        "已发现系统采集任务：%s",
        "、".join("{}({})={}秒".format(task.zh_name, task.name, task.interval) for task in tasks),
    )
    return tasks
