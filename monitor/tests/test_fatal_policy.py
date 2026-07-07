"""验证 Pico 固件致命异常的自动重启策略。"""

import sys
import unittest
from pathlib import Path


PICO_ROOT = Path(__file__).resolve().parents[2] / "picoRP2040"
if str(PICO_ROOT) not in sys.path:
    sys.path.insert(0, str(PICO_ROOT))

from fatal_policy import should_restart_after_fatal


class FatalPolicyTest(unittest.TestCase):
    """覆盖需要重启和应继续停留诊断状态的异常。"""

    def test_canvas_capacity_error_requires_restart(self):
        """确认未被自定义样式回退逻辑处理的画布错误仍要求重启。"""
        self.assertTrue(should_restart_after_fatal(ValueError("脏矩形超过画布容量")))

    def test_other_value_error_does_not_require_restart(self):
        """确认其他参数错误不会误触发自动重启。"""
        self.assertFalse(should_restart_after_fatal(ValueError("普通参数错误")))

    def test_memory_error_still_requires_restart(self):
        """确认既有内存不足自动重启策略保持有效。"""
        self.assertTrue(should_restart_after_fatal(MemoryError("内存不足")))


if __name__ == "__main__":
    unittest.main()
