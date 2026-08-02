"""
Unit Tests for SyncScheduler
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from zalo_drive_sync.core.scheduler import SyncScheduler


class TestSyncScheduler(unittest.TestCase):

    def setUp(self):
        self.calls = []
        self.func = lambda: self.calls.append(1)
        self.scheduler = SyncScheduler(interval_seconds=5, task_func=self.func)

    def tearDown(self):
        self.scheduler.stop()

    def test_interval_floor_min_1(self):
        self.assertEqual(SyncScheduler(0, self.func).interval, 1)
        self.assertEqual(SyncScheduler(-5, self.func).interval, 1)

    def test_interval_keeps_valid_value(self):
        self.assertEqual(SyncScheduler(10, self.func).interval, 10)

    def test_set_interval_clamps(self):
        self.scheduler.set_interval(30)
        self.assertEqual(self.scheduler.interval, 30)
        self.scheduler.set_interval(0)
        self.assertEqual(self.scheduler.interval, 1)
        self.scheduler.set_interval(-3)
        self.assertEqual(self.scheduler.interval, 1)

    def test_start_runs_task(self):
        self.scheduler.interval = 0.05
        self.scheduler.start()
        self.assertTrue(self.scheduler._thread and self.scheduler._thread.is_alive())
        deadline = time.monotonic() + 2.0
        while not self.calls and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.calls)  # task_func executed after start
        self.scheduler.stop()
        before = len(self.calls)
        time.sleep(0.15)
        self.assertEqual(len(self.calls), before)  # no more runs after stop

    def test_start_is_idempotent(self):
        self.scheduler.interval = 0.1
        self.scheduler.start()
        first_thread = self.scheduler._thread
        self.scheduler.start()
        self.assertIs(self.scheduler._thread, first_thread)

    def test_stop_joins_and_clears_thread(self):
        self.scheduler.interval = 0.1
        self.scheduler.start()
        self.scheduler.stop()
        self.assertIsNone(self.scheduler._thread)
        self.assertTrue(self.scheduler._stop_event.is_set())

    def test_stop_when_never_started_is_safe(self):
        self.scheduler.stop()
        self.assertIsNone(self.scheduler._thread)

    def test_restart_after_stop(self):
        self.scheduler.interval = 0.1
        self.scheduler.start()
        self.scheduler.stop()
        self.scheduler.start()
        self.assertTrue(self.scheduler._thread.is_alive())

    def test_task_exception_is_swallowed_and_loop_continues(self):
        executed = []
        done = threading.Event()

        def flaky():
            executed.append(1)
            if len(executed) == 1:
                raise RuntimeError("boom in task")
            done.set()

        self.scheduler.task_func = flaky
        self.scheduler.interval = 0.05
        self.scheduler.start()
        self.assertTrue(done.wait(2.0))
        self.assertGreaterEqual(len(executed), 2)

    def test_loop_stops_on_stop_event(self):
        self.scheduler.interval = 0.05
        self.scheduler.start()
        count_after_sleep = None
        self.scheduler.stop()
        before = len(self.calls)
        self.scheduler.stop()  # already stopped; no-op
        self.assertEqual(len(self.calls), before)

    def test_interval_attribute_is_public(self):
        self.scheduler.interval = 7
        self.assertEqual(self.scheduler.interval, 7)


if __name__ == "__main__":
    unittest.main()
