"""Verify metric histories use one point per monotonic second."""

import unittest
from collections import deque

from history import update_per_second


class PerSecondHistoryTest(unittest.TestCase):
    def test_repeated_samples_keep_the_current_second_peak(self):
        history = deque([0] * 4, maxlen=4)
        state = {}

        update_per_second(history, 10, state, now=100.1)
        update_per_second(history, 20, state, now=100.5)
        update_per_second(history, 5, state, now=100.9)

        self.assertEqual(list(history), [0, 0, 0, 20])

    def test_skipped_seconds_repeat_the_previous_value(self):
        history = deque([0] * 5, maxlen=5)
        state = {}

        update_per_second(history, 10, state, now=100.1)
        update_per_second(history, 40, state, now=103.0)

        self.assertEqual(list(history), [0, 10, 10, 10, 40])


if __name__ == "__main__":
    unittest.main()
