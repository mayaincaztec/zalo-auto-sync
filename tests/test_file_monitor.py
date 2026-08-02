"""
Unit Tests for ZaloFileHandler and FileMonitorManager
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from zalo_drive_sync.core.file_monitor import (
    WATCHDOG_AVAILABLE,
    FileMonitorManager,
    ZaloFileHandler,
)
from zalo_drive_sync.database.models import DownloadItem, SyncStatus


class FakeEvent:
    def __init__(self, src_path="", is_directory=False):
        self.src_path = src_path
        self.is_directory = is_directory


class TestZaloFileHandler(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.filepath = os.path.join(self.dir, "report.pdf")
        with open(self.filepath, "wb") as f:
            f.write(b"pdf-content")
        self.db = MagicMock()
        self.callback = MagicMock()
        self.logs = []
        self.handler = ZaloFileHandler(
            allowed_extensions=[".pdf", ".docx"],
            db_manager=self.db,
            file_callback=self.callback,
            log_callback=lambda lvl, msg: self.logs.append((lvl, msg)),
        )

    def tearDown(self):
        for root, _, files in os.walk(self.dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            os.rmdir(root)

    def _run_process(self, **patches):
        default_patches = {
            "wait_for_file_stability": MagicMock(return_value=True),
            "calculate_sha256": MagicMock(return_value="sha_123"),
        }
        default_patches.update(patches)
        with patch.multiple("zalo_drive_sync.core.file_monitor", **default_patches):
            self.handler.process_filepath(self.filepath)

    # --- on_created / on_modified ---

    def test_on_created_directory_ignored(self):
        with patch.object(self.handler, "process_filepath") as pf:
            self.handler.on_created(FakeEvent(src_path=self.filepath, is_directory=True))
        pf.assert_not_called()

    def test_on_created_file_forwards(self):
        with patch.object(self.handler, "process_filepath") as pf:
            self.handler.on_created(FakeEvent(src_path=self.filepath))
        pf.assert_called_once_with(self.filepath)

    def test_on_modified_directory_ignored(self):
        with patch.object(self.handler, "process_filepath") as pf:
            self.handler.on_modified(FakeEvent(src_path=self.filepath, is_directory=True))
        pf.assert_not_called()

    def test_on_modified_file_forwards(self):
        with patch.object(self.handler, "process_filepath") as pf:
            self.handler.on_modified(FakeEvent(src_path=self.filepath))
        pf.assert_called_once_with(self.filepath)

    # --- process_filepath branch coverage ---

    def test_process_missing_file_returns(self):
        self.handler.process_filepath(os.path.join(self.dir, "ghost.pdf"))
        self.db.add_item.assert_not_called()

    def test_process_temp_extension_skipped(self):
        for ext in [".tmp", ".crdownload", ".part", ".download"]:
            p = os.path.join(self.dir, "file" + ext)
            open(p, "wb").close()
            self.handler.process_filepath(p)
        self.db.add_item.assert_not_called()
        self.callback.assert_not_called()

    def test_process_disallowed_extension_skipped(self):
        p = os.path.join(self.dir, "note.exe")
        open(p, "wb").close()
        self.handler.process_filepath(p)
        self.db.add_item.assert_not_called()
        self.assertTrue(any("not in allowed list" in m for _, m in self.logs))

    def test_process_extension_matching_case_insensitive(self):
        p = os.path.join(self.dir, "UPPER.PDF")
        open(p, "wb").close()
        self.db.is_file_uploaded.return_value = False
        self.db.get_item_by_hash.return_value = None
        self.db.add_item.return_value = 1
        self._run_process()
        self.db.add_item.assert_called_once()

    def test_process_unstable_file_skipped(self):
        with patch("zalo_drive_sync.core.file_monitor.wait_for_file_stability", return_value=False):
            self.handler.process_filepath(self.filepath)
        self.db.add_item.assert_not_called()
        self.assertTrue(any("still locked" in m for _, m in self.logs))

    def test_process_empty_file_skipped(self):
        empty = os.path.join(self.dir, "empty.pdf")
        open(empty, "wb").close()
        with patch("zalo_drive_sync.core.file_monitor.wait_for_file_stability", return_value=True):
            self.handler.process_filepath(empty)
        self.db.add_item.assert_not_called()
        self.assertTrue(any("empty (0 bytes)" in m for _, m in self.logs))

    def test_process_hash_error_skipped(self):
        with patch("zalo_drive_sync.core.file_monitor.wait_for_file_stability", return_value=True):
            with patch("zalo_drive_sync.core.file_monitor.calculate_sha256", side_effect=OSError("read fail")):
                self.handler.process_filepath(self.filepath)
        self.db.add_item.assert_not_called()
        self.assertTrue(any("Failed to compute" in m for _, m in self.logs))

    def test_process_duplicate_hash_skipped(self):
        self.db.is_file_uploaded.return_value = True
        self._run_process()
        self.db.add_item.assert_not_called()
        self.assertTrue(any("already been uploaded" in m for _, m in self.logs))

    def test_process_existing_completed_skipped(self):
        existing = DownloadItem(status=SyncStatus.COMPLETED)
        self.db.is_file_uploaded.return_value = False
        self.db.get_item_by_hash.return_value = existing
        self._run_process()
        self.db.add_item.assert_not_called()
        self.assertTrue(any("already marked completed" in m for _, m in self.logs))

    def test_process_existing_pending_not_skipped(self):
        existing = DownloadItem(status=SyncStatus.PENDING)
        self.db.is_file_uploaded.return_value = False
        self.db.get_item_by_hash.return_value = existing
        self.db.add_item.return_value = 42
        self._run_process()
        self.db.add_item.assert_called_once()
        self.assertEqual(self.callback.call_count, 1)
        item = self.callback.call_args[0][0]
        self.assertEqual(item.id, 42)
        self.assertEqual(item.filename, "report.pdf")
        self.assertEqual(item.status, SyncStatus.PENDING)

    def test_process_normal_file_queues(self):
        self.db.is_file_uploaded.return_value = False
        self.db.get_item_by_hash.return_value = None
        self.db.add_item.return_value = 7
        self._run_process()
        self.db.add_item.assert_called_once()
        self.callback.assert_called_once()
        item = self.callback.call_args[0][0]
        self.assertEqual(item.filepath, self.filepath)
        self.assertEqual(item.hash, "sha_123")
        self.assertEqual(item.status, SyncStatus.PENDING)
        self.assertTrue(any("Queuing file" in m for _, m in self.logs))

    def test_allowed_extensions_normalized_lowercase(self):
        h = ZaloFileHandler([".PDF", " .DOCX "], self.db, self.callback)
        self.assertEqual(h.allowed_extensions, [".pdf", ".docx"])

    def test_log_without_callback_is_noop(self):
        h = ZaloFileHandler([".pdf"], self.db, self.callback)
        h.log("INFO", "silent")  # must not raise

    def test_process_works_without_log_callback(self):
        h = ZaloFileHandler([".pdf"], self.db, self.callback)
        self.db.is_file_uploaded.return_value = False
        self.db.get_item_by_hash.return_value = None
        self.db.add_item.return_value = 1
        with patch("zalo_drive_sync.core.file_monitor.wait_for_file_stability", return_value=True):
            with patch("zalo_drive_sync.core.file_monitor.calculate_sha256", return_value="sha"):
                h.process_filepath(self.filepath)
        self.db.add_item.assert_called_once()

    def test_watchdog_fallback_when_imports_missing(self):
        code = (
            "import sys\n"
            "sys.modules['watchdog'] = None\n"
            "sys.modules['watchdog.events'] = None\n"
            "sys.modules['watchdog.observers'] = None\n"
            "import zalo_drive_sync.core.file_monitor as m\n"
            "assert m.WATCHDOG_AVAILABLE is False\n"
            "assert isinstance(m.ZaloFileHandler, type)\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": os.pathsep.join([os.path.dirname(os.path.dirname(os.path.dirname(__file__))), os.environ.get("PYTHONPATH", "")])}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestFileMonitorManager(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = MagicMock()
        self.callback = MagicMock()
        self.logs = []
        self.manager = FileMonitorManager(
            directory=self.dir,
            extensions=[".pdf"],
            db_manager=self.db,
            file_callback=self.callback,
            log_callback=lambda lvl, msg: self.logs.append((lvl, msg)),
        )

    def tearDown(self):
        try:
            self.manager.stop()
        except Exception:
            pass
        for root, _, files in os.walk(self.dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            os.rmdir(root)

    def test_start_without_watchdog_returns_false(self):
        with patch("zalo_drive_sync.core.file_monitor.WATCHDOG_AVAILABLE", False):
            self.assertFalse(self.manager.start())
        self.assertFalse(self.manager.is_running)
        self.assertTrue(any("Watchdog package not available" in m for _, m in self.logs))

    def test_start_without_watchdog_and_no_log_callback(self):
        manager = FileMonitorManager(
            directory=self.dir, extensions=[".pdf"],
            db_manager=self.db, file_callback=self.callback,
        )
        with patch("zalo_drive_sync.core.file_monitor.WATCHDOG_AVAILABLE", False):
            self.assertFalse(manager.start())
        self.assertFalse(manager.is_running)

    def test_start_without_log_callback(self):
        manager = FileMonitorManager(
            directory=self.dir, extensions=[".pdf"],
            db_manager=self.db, file_callback=self.callback,
        )
        with patch("zalo_drive_sync.core.file_monitor.Observer") as obs_cls:
            with patch.object(manager, "scan_existing_files"):
                self.assertTrue(manager.start())
        self.assertTrue(manager.is_running)

    def test_stop_without_log_callback(self):
        manager = FileMonitorManager(
            directory=self.dir, extensions=[".pdf"],
            db_manager=self.db, file_callback=self.callback,
        )
        with patch("zalo_drive_sync.core.file_monitor.Observer") as obs_cls:
            with patch.object(manager, "scan_existing_files"):
                manager.start()
            manager.stop()
        self.assertFalse(manager.is_running)

    def test_scan_existing_files_error_without_log_callback(self):
        manager = FileMonitorManager(
            directory=self.dir, extensions=[".pdf"],
            db_manager=self.db, file_callback=self.callback,
        )
        with patch("os.scandir", side_effect=OSError("permission denied")):
            manager.scan_existing_files(MagicMock())  # must not raise

    def test_start_creates_missing_directory(self):
        missing = os.path.join(self.dir, "sub", "nested")
        self.manager.directory = missing
        with patch("zalo_drive_sync.core.file_monitor.Observer") as obs_cls:
            obs_cls.return_value.schedule = MagicMock()
            obs_cls.return_value.start = MagicMock()
            obs_cls.return_value.join = MagicMock()
            with patch.object(self.manager, "scan_existing_files") as scan:
                self.assertTrue(self.manager.start())
                scan.assert_called_once()
        self.assertTrue(os.path.exists(missing))

    def test_start_schedules_and_starts_observer(self):
        with patch("zalo_drive_sync.core.file_monitor.Observer") as obs_cls:
            observer = obs_cls.return_value
            with patch.object(self.manager, "scan_existing_files") as scan:
                self.assertTrue(self.manager.start())
                observer.schedule.assert_called_once()
                observer.start.assert_called_once()
                self.assertTrue(self.manager.is_running)
                self.assertIs(self.manager.observer, observer)
                scan.assert_called_once()

    def test_start_logs_monitoring_message(self):
        with patch("zalo_drive_sync.core.file_monitor.Observer"):
            with patch.object(self.manager, "scan_existing_files"):
                self.manager.start()
        self.assertTrue(any("Started monitoring folder" in m for _, m in self.logs))

    def test_stop_stops_observer(self):
        with patch("zalo_drive_sync.core.file_monitor.Observer") as obs_cls:
            observer = obs_cls.return_value
            with patch.object(self.manager, "scan_existing_files"):
                self.manager.start()
            self.manager.stop()
            observer.stop.assert_called_once()
            observer.join.assert_called_once()
            self.assertFalse(self.manager.is_running)
            self.assertTrue(any("Stopped file monitor" in m for _, m in self.logs))

    def test_stop_when_not_running_noop(self):
        self.manager.stop()  # observer None, is_running False
        self.assertFalse(self.manager.is_running)

    def test_scan_existing_files_processes_files(self):
        with open(os.path.join(self.dir, "existing.pdf"), "wb") as f:
            f.write(b"old file")
        handler = MagicMock()
        self.manager.scan_existing_files(handler)
        handler.process_filepath.assert_called_once()

    def test_scan_existing_files_skips_directories(self):
        os.makedirs(os.path.join(self.dir, "subfolder"))
        handler = MagicMock()
        self.manager.scan_existing_files(handler)
        handler.process_filepath.assert_not_called()

    def test_scan_existing_files_error_logged(self):
        with patch("os.scandir", side_effect=OSError("permission denied")):
            self.manager.scan_existing_files(MagicMock())
        self.assertTrue(any("Error scanning existing files" in m for _, m in self.logs))


if __name__ == "__main__":
    unittest.main()
