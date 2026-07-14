"""验证仪表盘批量刷新遵守区域数量和软时间预算。"""

import sys
import unittest
from pathlib import Path
from unittest import mock


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from dashboard import DashboardRenderer  # noqa: E402


class DashboardRenderBudgetTest(unittest.TestCase):
    """覆盖批量区域刷新在时间预算边界上的停止行为。"""

    def test_batch_stops_after_time_budget_at_region_boundary(self):
        """确认达到软预算后停止批次且不会切断正在绘制的区域。"""
        renderer = DashboardRenderer.__new__(DashboardRenderer)
        renderer._completion_pending = False
        renderer.is_rendering = mock.Mock(side_effect=[True, True, True])
        renderer.update = mock.Mock(return_value=False)

        with mock.patch(
            "dashboard.time.ticks_us",
            side_effect=[0, 30000, 60000],
            create=True,
        ), mock.patch(
            "dashboard.time.ticks_diff",
            side_effect=lambda current, started: current - started,
            create=True,
        ):
            completed = renderer.update_pending(
                max_regions=8,
                time_budget_us=50000,
            )

        self.assertFalse(completed)
        self.assertEqual(renderer.update.call_count, 2)

    def test_batch_stops_at_region_limit_without_time_budget(self):
        """确认未配置时间预算时仍严格遵守最大区域数量。"""
        renderer = DashboardRenderer.__new__(DashboardRenderer)
        renderer._completion_pending = False
        renderer.is_rendering = mock.Mock(
            side_effect=[True, True, True, True]
        )
        renderer.update = mock.Mock(return_value=False)

        with mock.patch(
            "dashboard.time.ticks_us", return_value=0, create=True
        ):
            completed = renderer.update_pending(max_regions=3)

        self.assertFalse(completed)
        self.assertEqual(renderer.update.call_count, 3)


if __name__ == "__main__":
    unittest.main()
