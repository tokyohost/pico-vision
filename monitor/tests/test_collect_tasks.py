"""验证后台采集线程池、任务调度和无锁快照发布行为。"""

import threading
import types
import unittest
from collections import deque
from unittest import mock

import psutil  # 提前加载真实依赖，避免测试替身污染后续测试模块。

from collectTask.coordinator import CollectionCoordinator
from collectTask.executor import BoundedElasticThreadPool, TaskRejectedError
from collectTask.result_store import LockFreeSnapshotStore
from collectTask.system_tasks import system_task_defaults, system_task_zh_names
from collectTask.tasks.disk_common import (
    DISK_CAPACITY_HEALTH_FIELDS,
    DISK_RATE_FIELDS,
    DISK_TEMPERATURE_FIELDS,
    publish_disk_snapshot,
)
from collectTask.tasks.cpu_memory import CpuMemoryTask
from collectTask.tasks.gpu import GpuTask
from collectTask.tasks.power import PowerTask


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

    def test_sensor_host_available_skips_cpu_memory_fallback_fields(self):
        """确认 SensorHost 有效时 CPU 和内存降级任务不发布覆盖字段。"""
        collector = types.SimpleNamespace(
            histories={"cpu": deque(maxlen=24), "memory": deque(maxlen=24)},
            history_states={},
            is_sensor_host_metric_available=lambda name: name in {"cpu", "memory"},
        )
        task = CpuMemoryTask(collector)

        with mock.patch.object(task, "_cpu_percent") as cpu_percent, \
                mock.patch("collectTask.tasks.cpu_memory.psutil.virtual_memory", create=True) as virtual_memory:
            fragment = task.collect()

        self.assertEqual(fragment, {})
        cpu_percent.assert_not_called()
        virtual_memory.assert_not_called()

    def test_cpu_memory_fallback_only_fills_missing_sensor_host_metric(self):
        """确认 SensorHost 缺少内存时 CPU 避让而内存继续由 psutil 补齐。"""
        collector = types.SimpleNamespace(
            histories={"cpu": deque(maxlen=24), "memory": deque(maxlen=24)},
            history_states={},
            is_sensor_host_metric_available=lambda name: name == "cpu",
            _cpu_frequency_ghz=mock.Mock(return_value=4.0),
            _cpu_temperature=mock.Mock(return_value=50.0),
        )
        memory = types.SimpleNamespace(percent=25.5, used=255, total=1000)
        task = CpuMemoryTask(collector)

        with mock.patch.object(task, "_cpu_percent") as cpu_percent, \
                mock.patch("collectTask.tasks.cpu_memory.psutil.virtual_memory", return_value=memory, create=True):
            fragment = task.collect()

        self.assertNotIn("cpu", fragment)
        self.assertEqual(fragment["memory"]["percent"], 25.5)
        cpu_percent.assert_not_called()

    def test_sensor_host_available_skips_gpu_and_power_fallback(self):
        """确认 SensorHost 有效时 GPU 和功耗降级任务不发布覆盖字段。"""
        collector = types.SimpleNamespace(
            is_sensor_host_metric_available=lambda name: name in {"gpu", "power"},
            gpu_monitor=mock.Mock(),
            power_monitor=mock.Mock(),
        )

        self.assertEqual(GpuTask(collector).collect(), {})
        self.assertEqual(PowerTask(collector).collect(), {})
        collector.gpu_monitor.snapshot.assert_not_called()
        collector.power_monitor.snapshot.assert_not_called()

    def test_disk_tasks_are_split_with_expected_default_intervals(self):
        """确认磁盘容量健康、温度和读写速率任务拥有独立默认频率。"""
        defaults = system_task_defaults()
        zh_names = system_task_zh_names()
        self.assertEqual(defaults["disk_capacity_health"], 60.0)
        self.assertEqual(defaults["disk_temperature"], 5.0)
        self.assertEqual(defaults["disk_rate"], 1.0)
        self.assertEqual(zh_names["disk_capacity_health"], "磁盘容量与健康采集")
        self.assertNotIn("磁盘采集", defaults)

    def test_split_disk_task_fragments_keep_previous_fields(self):
        """确认拆分后的磁盘任务按字段合并，不覆盖其他任务已有结果。"""
        collector = types.SimpleNamespace()
        capacity = publish_disk_snapshot(
            collector,
            disk={"percent": 50.0, "used_bytes": 50, "total_bytes": 100},
            disks=[{"name": "DISK0", "used_bytes": 50, "total_bytes": 100, "percent": 50.0, "health": 1}],
            physical_disks=[{"name": "DISK0", "health": 1}],
            disk_fields=DISK_CAPACITY_HEALTH_FIELDS,
            physical_fields=DISK_CAPACITY_HEALTH_FIELDS,
        )
        self.assertEqual(capacity["disks"][0]["health"], 1)
        temperature = publish_disk_snapshot(
            collector,
            disks=[{"name": "DISK0", "temperature_c": 42.0}],
            physical_disks=[{"name": "DISK0", "temperature_c": 42.0}],
            disk_fields=DISK_TEMPERATURE_FIELDS,
            physical_fields=DISK_TEMPERATURE_FIELDS,
        )
        self.assertEqual(temperature["disks"][0]["used_bytes"], 50)
        self.assertEqual(temperature["disks"][0]["temperature_c"], 42.0)
        rate = publish_disk_snapshot(
            collector,
            disks=[{"name": "DISK0", "read_bps": 10, "write_bps": 20}],
            physical_disks=[{"name": "DISK0", "read_bps": 10, "write_bps": 20}],
            disk_fields=DISK_RATE_FIELDS,
            physical_fields=DISK_RATE_FIELDS,
        )
        self.assertEqual(rate["disks"][0]["temperature_c"], 42.0)
        self.assertEqual(rate["disks"][0]["read_bps"], 10)
        replaced = publish_disk_snapshot(
            collector,
            disks=[{"name": "DISK0", "used_bytes": 60, "total_bytes": 100, "percent": 60.0, "health": 1}],
            physical_disks=[{"name": "DISK0", "health": 1}],
            disk_fields=DISK_CAPACITY_HEALTH_FIELDS,
            physical_fields=DISK_CAPACITY_HEALTH_FIELDS,
            replace_disks=True,
            replace_physical_disks=True,
        )
        self.assertEqual(len(replaced["disks"]), 1)
        self.assertEqual(replaced["disks"][0]["temperature_c"], 42.0)
        self.assertEqual(replaced["disks"][0]["used_bytes"], 60)

    def test_task_completion_publishes_fragment_immediately(self):
        """确认协调器无需等待同批其他任务即可更新快照。"""
        collector = mock.Mock()
        store = LockFreeSnapshotStore({"version": 1})
        coordinator = CollectionCoordinator.__new__(CollectionCoordinator)
        coordinator.result_store = store
        coordinator.result_transform = None
        task = mock.Mock()
        task.name = "cpu_memory"
        task.zh_name = "CPU与内存采集"
        task.collect.return_value = {"cpu": {"percent": 42.0}}
        task.scheduled = True
        coordinator.executor = BoundedElasticThreadPool()
        with self.assertLogs("pico-monitor.collector", level="DEBUG") as logs:
            coordinator._execute_and_publish(task)
        self.assertEqual(store.snapshot()["cpu"]["percent"], 42.0)
        self.assertFalse(task.scheduled)
        self.assertIn("采集任务开始：任务=CPU与内存采集(cpu_memory)", logs.output[0])
        self.assertIn("采集任务完成：任务=CPU与内存采集(cpu_memory)", logs.output[1])
        self.assertIn("线程池[核心=3，最大=8", logs.output[1])


if __name__ == "__main__":
    unittest.main()
