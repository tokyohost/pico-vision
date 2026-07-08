"""协调周期调度、任务丢弃和单项采样结果即时发布。"""

import logging
import time

from .executor import BoundedElasticThreadPool, TaskRejectedError
from .system_tasks import CallbackCollectionTask, create_system_tasks


LOGGER = logging.getLogger("pico-monitor.collector")


class CollectionCoordinator:
    """将独立采集子任务提交到有界弹性线程池并即时发布结果。"""

    def __init__(self, collector, result_store, result_transform=None, extra_tasks=()):
        """创建默认 3 核心、8 最大、100 等待任务的采集协调器。"""
        self.result_store = result_store
        self.result_transform = result_transform
        self.tasks = create_system_tasks(collector) + tuple(
            CallbackCollectionTask(collector, callback, name)
            for name, callback in extra_tasks
        )
        self.executor = BoundedElasticThreadPool(core_workers=3, max_workers=8, queue_capacity=100)
        LOGGER.info("采集线程池已初始化：%s", self._pool_state_text())

    def schedule(self):
        """提交当前空闲的全部子任务，已在等待或执行的任务不会重复入队。"""
        for task in self.tasks:
            if task.scheduled:
                continue
            task.scheduled = True
            try:
                self.executor.submit(self._execute_and_publish, task)
                LOGGER.info("采集任务已提交：任务=%s，%s", task.name, self._pool_state_text())
            except TaskRejectedError:
                task.scheduled = False
                LOGGER.warning("采集任务被丢弃：任务=%s，%s", task.name, self._pool_state_text())

    def close(self, wait=True):
        """关闭采集线程池，并按需等待已经接受的任务执行完毕。"""
        LOGGER.info("采集线程池准备关闭：%s", self._pool_state_text())
        self.executor.shutdown(wait=wait)
        LOGGER.info("采集线程池已关闭：%s", self._pool_state_text())

    def _pool_state_text(self):
        """把线程池实时状态格式化为统一的中文日志文本。"""
        state = self.executor.state()
        return (
            "线程池[核心={core_workers}，最大={max_workers}，已创建={workers}，"
            "活跃={active}，空闲={idle}，排队={queued}/{queue_capacity}]"
        ).format(**state)

    def _execute_and_publish(self, task):
        """执行单个子任务，并在完成时立即无锁发布对应采样结果。"""
        started = time.monotonic()
        LOGGER.info("采集任务开始：任务=%s，%s", task.name, self._pool_state_text())
        try:
            fragment = task.collect()
            if self.result_transform is not None:
                fragment = self.result_transform(fragment)
            self.result_store.publish(fragment)
            LOGGER.info(
                "采集任务完成：任务=%s，耗时=%.3f秒，更新字段=%s，%s",
                task.name,
                time.monotonic() - started,
                "、".join(fragment.keys()) or "无",
                self._pool_state_text(),
            )
        except Exception as error:
            LOGGER.exception(
                "采集任务失败：任务=%s，耗时=%.3f秒，错误=%s，%s",
                task.name,
                time.monotonic() - started,
                error,
                self._pool_state_text(),
            )
        finally:
            task.scheduled = False
