"""
Periodic Scheduler Module
Provides timer thread for scheduled directory scans and housekeeping tasks.
"""

import threading
import time
from typing import Callable, Optional


class SyncScheduler:
    """Periodic timer scheduler for running background sync routines."""

    def __init__(self, interval_seconds: int, task_func: Callable[[], None]):
        self.interval = max(1, interval_seconds)
        self.task_func = task_func
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Starts periodic task."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="SyncSchedulerThread")
        self._thread.start()

    def stop(self):
        """Stops periodic task."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def set_interval(self, new_interval: int):
        """Updates timer interval dynamically."""
        self.interval = max(1, new_interval)

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self.task_func()
            except Exception:
                pass
            self._stop_event.wait(self.interval)
