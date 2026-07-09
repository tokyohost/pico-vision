"""实现具有核心线程、突发线程和有界等待队列的采集线程池。"""

import logging
import queue
import threading


LOGGER = logging.getLogger("pico-monitor.collector")


class TaskRejectedError(RuntimeError):
    """表示线程池和等待队列均已满，当前采集任务已被丢弃。"""


class BoundedElasticThreadPool:
    """运行采集任务，并在队列饱和时按需创建有限数量的突发线程。"""

    _STOP = object()

    def __init__(self, core_workers=3, max_workers=8, queue_capacity=100):
        """校验容量并初始化尚未启动工作线程的有界线程池。"""
        if not 0 < core_workers <= max_workers:
            raise ValueError("核心线程数必须大于零且不能超过最大线程数")
        if queue_capacity <= 0:
            raise ValueError("任务队列长度必须大于零")
        self.core_workers = core_workers
        self.max_workers = max_workers
        self.queue_capacity = queue_capacity
        self._tasks = queue.Queue(maxsize=queue_capacity)
        self._workers = []
        self._active_tasks = 0
        self._shutdown = False

    @property
    def worker_count(self):
        """返回线程池已经创建的工作线程数量。"""
        return len(self._workers)

    @property
    def queued_task_count(self):
        """返回当前正在等待工作线程领取的任务数量。"""
        return self._tasks.qsize()

    @property
    def active_task_count(self):
        """返回当前正在工作线程中执行的任务数量。"""
        return self._active_tasks

    def state(self):
        """返回用于运行日志的线程池实时状态快照。"""
        workers = self.worker_count
        active = self.active_task_count
        return {
            "core_workers": self.core_workers,
            "max_workers": self.max_workers,
            "workers": workers,
            "active": active,
            "idle": max(0, workers - active),
            "queued": self.queued_task_count,
            "queue_capacity": self.queue_capacity,
        }

    def submit(self, function, *arguments, **keywords):
        """提交任务；工作线程全忙时优先扩容，达到上限后再进入等待队列。"""
        if self._shutdown:
            raise RuntimeError("采集线程池已经关闭")
        work_item = (function, arguments, keywords)
        if self.worker_count < self.core_workers:
            self._start_worker(work_item)
            return True
        if self.active_task_count >= self.worker_count and self.worker_count < self.max_workers:
            self._start_worker(work_item)
            return True
        try:
            self._tasks.put_nowait(work_item)
            return True
        except queue.Full:
            if self.worker_count < self.max_workers:
                self._start_worker(work_item)
                return True
            raise TaskRejectedError("采集线程池队列已满，任务已丢弃")

    def shutdown(self, wait=True):
        """停止接收新任务，并通知全部工作线程在已有任务完成后退出。"""
        if self._shutdown:
            return
        self._shutdown = True
        for _ in self._workers:
            self._tasks.put(self._STOP)
        if wait:
            for worker in tuple(self._workers):
                worker.join()

    def _start_worker(self, initial_work_item=None):
        """创建一个守护工作线程，并允许其直接执行触发扩容的任务。"""
        worker = threading.Thread(target=self._worker_loop, args=(initial_work_item,), name="指标采集池-{}".format(self.worker_count + 1), daemon=True)
        self._workers.append(worker)
        worker.start()

    def _worker_loop(self, work_item):
        """持续执行队列任务，并隔离单个任务抛出的未处理异常。"""
        while True:
            if work_item is None:
                work_item = self._tasks.get()
            if work_item is self._STOP:
                return
            function, arguments, keywords = work_item
            self._active_tasks += 1
            try:
                function(*arguments, **keywords)
            except Exception:
                LOGGER.exception("采集子任务发生未处理异常")
            finally:
                self._active_tasks = max(0, self._active_tasks - 1)
                work_item = None
