"""协调多频率调度、任务丢弃和单项采样结果即时发布。"""

import logging
import time

from .executor import BoundedElasticThreadPool, TaskRejectedError
from .system_tasks import CallbackCollectionTask, create_system_tasks, system_task_aliases


LOGGER = logging.getLogger("pico-monitor.collector")


class CollectionCoordinator:
    """将独立采集子任务提交到有界弹性线程池并即时发布结果。"""

    def __init__(
        self,
        collector,
        result_store,
        result_transform=None,
        extra_tasks=(),
        task_intervals=None,
    ):
        """创建默认 3 核心、8 最大、100 等待任务的采集协调器。"""
        self.result_store = result_store
        self.result_transform = result_transform
        self.tasks = create_system_tasks(collector) + tuple(
            self._create_callback_task(collector, item)
            for item in extra_tasks
        )
        self._apply_task_intervals(task_intervals or {})
        self.executor = BoundedElasticThreadPool(core_workers=3, max_workers=8, queue_capacity=100)
        LOGGER.info("采集线程池已初始化：%s", self._pool_state_text())
        LOGGER.info("采集任务频率：%s", self._task_interval_text())

    def schedule(self):
        """提交当前到期且空闲的子任务，未到期或正在执行的任务不会重复入队。"""
        now = time.monotonic()
        for task in self.tasks:
            if not task.is_due(now):
                continue
            task.mark_scheduled(now)
            try:
                self.executor.submit(self._execute_and_publish, task)
                LOGGER.info(
                    "采集任务已提交：任务=%s，频率=%.3f秒，%s",
                    self._task_label(task),
                    task.interval,
                    self._pool_state_text(),
                )
            except TaskRejectedError:
                task.mark_finished()
                LOGGER.warning("采集任务被丢弃：任务=%s，%s", self._task_label(task), self._pool_state_text())

    def next_schedule_delay(self):
        """返回距离下一次任务到期的等待秒数，用于驱动多频率调度循环。"""
        now = time.monotonic()
        due_times = [
            task.next_run_time
            for task in self.tasks
            if not task.scheduled
        ]
        if not due_times:
            return min((task.interval for task in self.tasks), default=1.0)
        return max(0.0, min(due_times) - now)

    def close(self, wait=True):
        """关闭采集线程池，并按需等待已经接受的任务执行完毕。"""
        LOGGER.info("采集线程池准备关闭：%s", self._pool_state_text())
        self.executor.shutdown(wait=wait)
        LOGGER.info("采集线程池已关闭：%s", self._pool_state_text())

    @staticmethod
    def _create_callback_task(collector, item):
        """把额外采集配置转换为回调采集任务。"""
        if len(item) == 2:
            name, callback = item
            interval = 1.0
            zh_name = None
        elif len(item) == 3:
            name, callback, interval = item
            zh_name = None
        else:
            name, callback, interval, zh_name = item
        return CallbackCollectionTask(collector, callback, name, interval, zh_name)

    def _apply_task_intervals(self, task_intervals):
        """按任务名称应用外部采集频率配置。"""
        task_by_name = {task.name: task for task in self.tasks}
        aliases = system_task_aliases()
        for name, interval in task_intervals.items():
            name = aliases.get(name, name)
            task = task_by_name.get(name)
            if task is None:
                LOGGER.warning("忽略未知采集任务频率配置：任务=%s，频率=%s", name, interval)
                continue
            try:
                task.configure_interval(interval)
            except (TypeError, ValueError):
                LOGGER.warning("忽略无效采集任务频率配置：任务=%s，频率=%s", name, interval)

    def _task_interval_text(self):
        """把所有任务当前采集频率格式化为日志文本。"""
        return "、".join("{}={}秒".format(self._task_label(task), task.interval) for task in self.tasks)

    def _pool_state_text(self):
        """把线程池实时状态格式化为统一的中文日志文本。"""
        state = self.executor.state()
        return (
            "线程池[核心={core_workers}，最大={max_workers}，已创建={workers}，"
            "活跃={active}，空闲={idle}，排队={queued}/{queue_capacity}]"
        ).format(**state)

    @staticmethod
    def _task_label(task):
        """返回日志中使用的任务中文名称和英文标识。"""
        zh_name = getattr(task, "zh_name", task.name)
        return "{}({})".format(zh_name, task.name) if zh_name != task.name else task.name

    def _execute_and_publish(self, task):
        """执行单个子任务，并在完成时立即无锁发布对应采样结果。"""
        started = time.monotonic()
        task_label = self._task_label(task)
        LOGGER.info("采集任务开始：任务=%s，%s", task_label, self._pool_state_text())
        try:
            fragment = task.collect()
            if self.result_transform is not None:
                fragment = self.result_transform(fragment)
            self.result_store.publish(fragment)
            LOGGER.info(
                "采集任务完成：任务=%s，耗时=%.3f秒，更新字段=%s，%s",
                task_label,
                time.monotonic() - started,
                "、".join(fragment.keys()) or "无",
                self._pool_state_text(),
            )
        except Exception as error:
            LOGGER.exception(
                "采集任务失败：任务=%s，耗时=%.3f秒，错误=%s，%s",
                task_label,
                time.monotonic() - started,
                error,
                self._pool_state_text(),
            )
        finally:
            task.mark_finished()
            task.scheduled = False
