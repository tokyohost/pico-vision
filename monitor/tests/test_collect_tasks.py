"""验证后台采集线程池、任务调度和无锁快照发布行为。"""

import threading
import unittest
from unittest import mock

from collectTask.coordinator import CollectionCoordinator
from collectTask.executor import BoundedElasticThreadPool, TaskRejectedError
from collectTask.result_store import LockFreeSnapshotStore


class BoundedElasticThreadPoolTest(unittest.TestCase):
    """验证核心线程、突发线程、有界队列和拒绝策略。"""

    def test_default_pool_capacity_matches_collection_policy(self):
        """确认默认线程池采用 3 核心、8 最大和 100 队列容量。"""
        pool = BoundedElasticThreadPool()
        self.assertEqual(pool.core_workers, 3)
        self.assertEqual(pool.max_workers, 8)
        self.assertEqual(pool.queue_capacity, 100)
        self.assertEqual(pool.state(), {
            "core_workers": 3,
            "max_workers": 8,
            "workers": 0,
            "active": 0,
            "idle": 0,
            "queued": 0,
            "queue_capacity": 100,
        })
        pool.shutdown()

    def test_full_pool_rejects_task_after_eight_workers_and_one_hundred_queued(self):
        """确认线程和队列均饱和后直接丢弃新任务。"""
        pool = BoundedElasticThreadPool()
        release = threading.Event()
        started = threading.Event()

        def blocking_task():
            """占用工作线程，直到测试允许任务退出。"""
            started.set()
            release.wait(2)

        for _ in range(3):
            pool.submit(blocking_task)
        self.assertTrue(started.wait(1))
        for _ in range(100):
            pool.submit(lambda: None)
        for _ in range(5):
            pool.submit(blocking_task)
        with self.assertRaises(TaskRejectedError):
            pool.submit(lambda: None)
        self.assertEqual(pool.worker_count, 8)
        self.assertEqual(pool.queued_task_count, 100)
        release.set()
        pool.shutdown()


class LockFreeSnapshotStoreTest(unittest.TestCase):
    """验证采样片段发布不会修改发送方已经取得的旧快照。"""

    def test_publish_updates_only_corresponding_result(self):
        """确认不同任务的结果均被保留且旧发送视图保持不变。"""
        store = LockFreeSnapshotStore({"cpu": {"percent": None}, "network": {"online": False}})
        sending = store.snapshot()
        store.publish({"cpu": {"percent": 30.0}})
        store.publish({"network": {"online": True}})
        latest = store.snapshot()
        self.assertIsNone(sending["cpu"]["percent"])
        self.assertEqual(latest["cpu"]["percent"], 30.0)
        self.assertTrue(latest["network"]["online"])


class CollectionCoordinatorTest(unittest.TestCase):
    """验证单个采集子任务完成后立即发布对应结果。"""

    def test_task_completion_publishes_fragment_immediately(self):
        """确认协调器无需等待同批其他任务即可更新快照。"""
        collector = mock.Mock()
        store = LockFreeSnapshotStore({"version": 1})
        coordinator = CollectionCoordinator.__new__(CollectionCoordinator)
        coordinator.result_store = store
        coordinator.result_transform = None
        task = mock.Mock()
        task.name = "CPU与内存采集"
        task.collect.return_value = {"cpu": {"percent": 42.0}}
        task.scheduled = True
        coordinator.executor = BoundedElasticThreadPool()
        with self.assertLogs("pico-monitor.collector", level="INFO") as logs:
            coordinator._execute_and_publish(task)
        self.assertEqual(store.snapshot()["cpu"]["percent"], 42.0)
        self.assertFalse(task.scheduled)
        self.assertIn("采集任务开始：任务=CPU与内存采集", logs.output[0])
        self.assertIn("采集任务完成：任务=CPU与内存采集", logs.output[1])
        self.assertIn("线程池[核心=3，最大=8", logs.output[1])


if __name__ == "__main__":
    unittest.main()
