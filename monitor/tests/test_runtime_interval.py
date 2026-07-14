"""验证主监控服务的发送间隔计时语义。"""

from types import SimpleNamespace
import threading
import unittest
from unittest import mock

from monitor_core.runtime_operations import RuntimeOperationsMixin


class RuntimeIntervalHarness(RuntimeOperationsMixin):
    """提供发送间隔测试所需的最小运行时对象。"""

    def __init__(self):
        """初始化基础发送间隔和停止事件。"""
        self.arguments = SimpleNamespace(adaptive_transmit=False, interval=0.5)
        self.stopping = threading.Event()


class RuntimeIntervalTestCase(unittest.TestCase):
    """校验发送完成与发送间隔等待的先后顺序。"""

    def test_transmission_is_not_idle_after_worker_takes_snapshot(self):
        """确认快照已出队但尚未发送完成时不会被误判为空闲。"""
        service = RuntimeIntervalHarness()
        service._ensure_transmit_state()
        service._transmit_queue.put_nowait({"version": 1})
        service._transmit_queue.get_nowait()

        def finish_transmission(timeout):
            """模拟后台发送线程在首次轮询等待期间完成快照。"""
            self.assertEqual(0.05, timeout)
            service._transmit_queue.task_done()

        service.stopping.wait = mock.Mock(side_effect=finish_transmission)

        service._wait_for_transmit_idle()

        service.stopping.wait.assert_called_once_with(0.05)

    def test_interval_starts_after_previous_transmission_finishes(self):
        """确认发送完成后才开始等待完整的有效发送间隔。"""
        service = RuntimeIntervalHarness()
        call_order = []
        service._wait_for_transmit_idle = mock.Mock(
            side_effect=lambda: call_order.append("发送完成")
        )
        service._effective_transmit_interval = mock.Mock(return_value=0.5)
        service._wait_for_interval_or_transmit_error = mock.Mock(
            side_effect=lambda timeout: call_order.append(("等待间隔", timeout))
        )

        service._wait_for_next_transmission()

        self.assertEqual(["发送完成", ("等待间隔", 0.5)], call_order)


if __name__ == "__main__":
    unittest.main()
