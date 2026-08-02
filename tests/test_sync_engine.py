"""
Unit Tests for ZaloGroupSyncEngine
"""

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.core.sync_engine import ZaloGroupSyncEngine
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import SyncStatus
from zalo_drive_sync.services.zalo_controller import GroupFile


class FakeDateTime:
    """Stand-in for datetime in sync_engine; now() returns a fixed value."""
    fixed = datetime(2026, 1, 1, 9, 0)

    @classmethod
    def now(cls):
        return cls.fixed


def make_group_file(fid="f1", name="doc.pdf", size=100, group="LOIMINH"):
    return GroupFile(
        file_id=fid,
        message_id=f"msg_{fid}",
        filename=name,
        filesize=size,
        group_name=group,
    )


class TestSyncEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        ConfigManager._instance = None
        self.config = ConfigManager(os.path.join(self.test_dir, "config.json"))
        self.config.set("group_name", "LOIMINH")
        self.config.set("check_interval", 5)
        self.config.set("gdrive_folder_id", "gdrive_1")
        self.config.set("download_timeout", 30)

        self.db = DatabaseManager(os.path.join(self.test_dir, "test.db"))
        self.gdrive = MagicMock()
        self.logs = []
        self.items = []

        self.sample_file = os.path.join(self.test_dir, "sample.pdf")
        with open(self.sample_file, "wb") as f:
            f.write(b"sample-content-for-hash")

        with patch("zalo_drive_sync.core.sync_engine.ZaloController") as ZC, \
             patch("zalo_drive_sync.core.sync_engine.UploadQueueManager") as UQ:
            self.engine = ZaloGroupSyncEngine(
                config_manager=self.config,
                db_manager=self.db,
                gdrive_service=self.gdrive,
                log_callback=lambda lvl, msg: self.logs.append((lvl, msg)),
                item_callback=lambda item, msg, pct: self.items.append((item, msg, pct)),
            )
            self.zc = ZC.return_value
            self.uq = UQ.return_value

    def tearDown(self):
        self.engine.stop()
        self.db.close()
        ConfigManager._instance = None
        for root, _, files in os.walk(self.test_dir, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass
            os.rmdir(root)

    def _has_log(self, needle):
        return any(needle in m for _, m in self.logs)

    # --- init / lifecycle ---

    def test_init_wires_dependencies(self):
        self.assertIs(self.engine.config_manager, self.config)
        self.assertIs(self.engine.db_manager, self.db)
        self.assertIs(self.engine.gdrive_service, self.gdrive)
        self.assertFalse(self.engine.is_running)
        self.assertIsNone(self.engine._thread)

    def test_init_controller_uses_log_callback(self):
        from zalo_drive_sync.core import sync_engine as se
        with patch.object(se, "ZaloController") as ZC:
            ZC.return_value = MagicMock()
            engine = ZaloGroupSyncEngine(self.config, self.db, self.gdrive)
            ZC.assert_called_once()
            call_kwargs = ZC.call_args.kwargs
            self.assertIn("log_callback", call_kwargs)
            self.assertEqual(call_kwargs["log_callback"], engine.log)

    def test_start_starts_queue_and_thread(self):
        self.engine.start()
        self.assertTrue(self.engine.is_running)
        self.uq.start.assert_called_once()
        self.assertIsNotNone(self.engine._thread)
        self.assertTrue(self._has_log("[Sync Engine] Started"))

    def test_start_is_idempotent(self):
        self.engine.start()
        thread1 = self.engine._thread
        self.engine.start()
        self.assertIs(self.engine._thread, thread1)
        self.uq.start.assert_called_once()

    def test_stop_stops_queue_and_bridge(self):
        self.engine.start()
        self.engine.stop()
        self.assertFalse(self.engine.is_running)
        self.uq.stop.assert_called_once()
        self.zc._stop_bridge.assert_called_once()
        self.assertIsNone(self.engine._thread)
        self.assertTrue(self._has_log("[Sync Engine] Stopped"))

    def test_stop_when_not_running_noop(self):
        self.engine.stop()
        self.uq.stop.assert_not_called()

    def test_stop_bridge_exception_swallowed(self):
        self.engine.is_running = True
        self.zc._stop_bridge.side_effect = Exception("bridge died")
        self.engine.stop()  # must not raise

    def test_stop_without_upload_queue(self):
        self.engine.is_running = True
        self.engine.upload_queue = None
        self.engine.stop()  # must not raise
        self.assertFalse(self.engine.is_running)

    def test_stop_without_controller(self):
        self.engine.is_running = True
        self.engine.zalo_controller = None
        self.engine.stop()  # must not raise
        self.assertFalse(self.engine.is_running)

    def test_stop_abort_exception_swallowed(self):
        self.engine.is_running = True
        self.zc.abort_waiting.side_effect = Exception("abort died")
        self.engine.stop()  # must not raise

    def test_stop_with_shared_controller_abort_exception_swallowed(self):
        shared = MagicMock()
        shared.abort_waiting.side_effect = Exception("abort died")
        with patch("zalo_drive_sync.core.sync_engine.UploadQueueManager") as UQ:
            UQ.return_value = MagicMock()
            engine = ZaloGroupSyncEngine(
                config_manager=self.config,
                db_manager=self.db,
                gdrive_service=self.gdrive,
                zalo_controller=shared,
            )
            engine.is_running = True
            engine.stop()  # must not raise

    def test_stop_with_shared_controller_keeps_bridge_alive(self):
        shared = MagicMock()
        with patch("zalo_drive_sync.core.sync_engine.UploadQueueManager") as UQ:
            UQ.return_value = MagicMock()
            engine = ZaloGroupSyncEngine(
                config_manager=self.config,
                db_manager=self.db,
                gdrive_service=self.gdrive,
                zalo_controller=shared,
            )
            self.assertFalse(engine._owns_controller)
            engine.start()
            engine.stop()
        shared.abort_waiting.assert_called_once()
        shared._stop_bridge.assert_not_called()
        self.assertFalse(engine.is_running)

    def test_init_accepts_shared_controller(self):
        shared = MagicMock()
        engine = ZaloGroupSyncEngine(
            config_manager=self.config,
            db_manager=self.db,
            gdrive_service=self.gdrive,
            zalo_controller=shared,
        )
        self.assertIs(engine.zalo_controller, shared)
        self.assertFalse(engine._owns_controller)

    def test_log_forwards_to_callback(self):
        self.engine.log("INFO", "hello world")
        self.assertIn(("INFO", "hello world"), self.logs)

    def test_on_queue_status_update_forwards(self):
        from zalo_drive_sync.database.models import DownloadItem
        item = DownloadItem(id=1, filename="x.pdf")
        self.engine.on_queue_status_update(item, "Uploading (50%)", 50)
        self.assertEqual(len(self.items), 1)
        self.assertEqual(self.items[0][1], "Uploading (50%)")
        self.assertEqual(self.items[0][2], 50)

    def test_on_queue_status_update_without_callback(self):
        engine = ZaloGroupSyncEngine(
            config_manager=self.config,
            db_manager=self.db,
            gdrive_service=self.gdrive,
        )
        engine.on_queue_status_update(None, "Uploading", 50)  # must not raise

    # --- schedule window ---

    def test_schedule_disabled_always_in_window(self):
        self.config.set("schedule_enabled", False)
        self.assertTrue(self.engine._in_schedule_window())

    def test_schedule_within_window(self):
        self.config.set("schedule_enabled", True)
        self.config.set("schedule_start", "08:00")
        self.config.set("schedule_end", "10:00")
        FakeDateTime.fixed = datetime(2026, 1, 1, 9, 0)
        with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
            self.assertTrue(self.engine._in_schedule_window())

    def test_schedule_outside_window(self):
        self.config.set("schedule_enabled", True)
        self.config.set("schedule_start", "08:00")
        self.config.set("schedule_end", "10:00")
        FakeDateTime.fixed = datetime(2026, 1, 1, 12, 0)
        with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
            self.assertFalse(self.engine._in_schedule_window())

    def test_schedule_cross_midnight(self):
        self.config.set("schedule_enabled", True)
        self.config.set("schedule_start", "22:00")
        self.config.set("schedule_end", "06:00")
        for hour, expected in [(23, True), (3, True), (12, False)]:
            FakeDateTime.fixed = datetime(2026, 1, 1, hour, 0)
            with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
                self.assertEqual(self.engine._in_schedule_window(), expected)

    def test_schedule_invalid_format_defaults_true(self):
        self.config.set("schedule_enabled", True)
        self.config.set("schedule_start", "bogus")
        self.config.set("schedule_end", "10:00")
        with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
            self.assertTrue(self.engine._in_schedule_window())

    # --- run_single_scan ---

    def test_run_single_scan_skips_outside_schedule(self):
        self.config.set("schedule_enabled", True)
        self.config.set("schedule_start", "08:00")
        self.config.set("schedule_end", "10:00")
        FakeDateTime.fixed = datetime(2026, 1, 1, 12, 0)
        with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
            self.engine.run_single_scan()
        self.zc.ensure_zalo_running.assert_not_called()
        self.assertTrue(self._has_log("Outside scheduled window"))

    def test_run_single_scan_no_group_name(self):
        self.config.set("group_name", "")
        self.engine.run_single_scan()
        self.zc.ensure_zalo_running.assert_not_called()
        self.assertTrue(self._has_log("No Zalo group name configured"))

    def test_run_single_scan_zalo_not_running(self):
        self.zc.ensure_zalo_running.return_value = False
        self.engine.run_single_scan()
        self.assertTrue(self._has_log("Could not connect to Zalo PC instance"))
        self.zc.open_group.assert_not_called()

    def test_run_single_scan_success_delegates_to_scan(self):
        self.zc.ensure_zalo_running.return_value = True
        with patch.object(self.engine, "_scan_single_group") as scan:
            self.engine.run_single_scan()
        scan.assert_called_once_with("LOIMINH", self.config.download_folder, 30, "gdrive_1")

    def test_run_single_scan_empty_gdrive_warns(self):
        self.config.set("gdrive_folder_id", "")
        self.zc.ensure_zalo_running.return_value = True
        with patch.object(self.engine, "_scan_single_group") as scan:
            self.engine.run_single_scan()
        scan.assert_called_once()
        self.assertTrue(self._has_log("Drive Folder ID is empty"))

    # --- _scan_single_group ---

    def test_scan_open_group_fails(self):
        self.zc.open_group.return_value = False
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.assertTrue(self._has_log("Failed to open group"))
        self.db.get_all_items(5)  # ensure no crash

    def test_scan_no_files(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = []
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.assertTrue(self._has_log("No files found"))

    def test_scan_download_failure_marks_failed(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = None
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.uq.add_item.assert_not_called()
        items = self.db.get_all_items(5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].drive_status, "failed")
        self.assertEqual(items[0].status, SyncStatus.FAILED)
        self.assertEqual(items[0].error_message, "Download timeout or file missing")

    def test_scan_download_file_missing_on_disk_marks_failed(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = os.path.join(self.test_dir, "ghost.pdf")
        self.engine.is_running = True
        with patch("zalo_drive_sync.core.sync_engine.os.path.exists", side_effect=lambda p: False):
            self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        items = self.db.get_all_items(5)
        self.assertEqual(items[0].drive_status, "failed")

    def test_scan_hash_already_uploaded_dedup(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        with patch("zalo_drive_sync.core.sync_engine.calculate_sha256", return_value="abc123"):
            with patch.object(self.db, "is_file_uploaded", return_value=True):
                self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.uq.add_item.assert_not_called()
        items = self.db.get_all_items(5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].drive_status, "completed")
        self.assertEqual(items[0].status, SyncStatus.COMPLETED)

    def test_scan_normal_flow_enqueues_upload(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(fid="f9", name="report.pdf")]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.uq.add_item.assert_called_once()
        kwargs = self.uq.add_item.call_args.kwargs
        self.assertEqual(kwargs["gdrive_folder_id"], "gdrive_1")
        self.assertEqual(kwargs["duplicate_action"], "rename")
        item = kwargs["item"]
        self.assertEqual(item.drive_status, "pending")
        self.assertEqual(item.group_name, "LOIMINH")
        self.assertEqual(item.filepath, self.sample_file)
        # db has the row with real hash
        rows = self.db.get_all_items(5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, SyncStatus.PENDING)

    def test_scan_no_gdrive_folder_skips_enqueue(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "")
        self.uq.add_item.assert_not_called()
        self.assertTrue(self._has_log("Google Drive folder ID not set"))

    def test_scan_hash_error_uses_fallback(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(fid="fb")]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        with patch("zalo_drive_sync.core.sync_engine.calculate_sha256", side_effect=OSError("read")):
            self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.uq.add_item.assert_called_once()
        item = self.uq.add_item.call_args.kwargs["item"]
        self.assertEqual(item.hash, "hash_fb")

    def test_scan_stops_when_engine_not_running(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(fid="a"), make_group_file(fid="b")]
        self.engine.is_running = False
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.zc.download_group_file.assert_not_called()
        self.uq.add_item.assert_not_called()
        self.assertTrue(self._has_log("already synced"))

    def test_scan_already_processed_file_skipped(self):
        self.zc.open_group.return_value = True
        gf = make_group_file(fid="known")
        self.zc.scan_group_files.return_value = [gf]
        # insert a known (completed) row first
        first = DownloadItemForTest(gf)
        self.db.add_item(first)
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        self.zc.download_group_file.assert_not_called()
        self.assertTrue(self._has_log("already processed"))

    def test_scan_completes_all_synced_message(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = None  # failed path
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.test_dir, 30, "gdrive_1")
        # new_files_count=1 -> "Processed 1 new file(s)"
        self.assertTrue(self._has_log("Processed 1 new file(s)"))

    # --- _sync_loop ---

    def test_sync_loop_runs_scan_and_stops_cleanly(self):
        with patch("zalo_drive_sync.core.sync_engine.time.sleep"):
            with patch.object(self.engine, "run_single_scan") as rs:
                self.engine.start()
                time.sleep(0.3)
                self.engine.stop()
        self.assertTrue(rs.called)

    def test_sync_loop_handles_scan_exception(self):
        with patch("zalo_drive_sync.core.sync_engine.time.sleep"):
            with patch.object(self.engine, "run_single_scan",
                              side_effect=RuntimeError("scan boom")):
                self.engine.start()
                time.sleep(0.3)
                self.engine.stop()
        self.assertTrue(self._has_log("Error during group scan iteration"))


class DownloadItemForTest:
    """Lightweight row for seeding the database in tests."""
    def __init__(self, gf):
        self.filename = gf.filename
        self.filepath = ""
        self.filesize = gf.filesize
        self.group_name = gf.group_name
        self.message_id = gf.message_id
        self.file_id = gf.file_id
        self.download_status = "downloaded"
        self.drive_status = "completed"
        self.created_time = None
        self.uploaded_time = None
        self.last_scan = None
        self.status = SyncStatus.COMPLETED
        self.hash = "existing_hash"
        self.drive_file_id = "did"
        self.error_message = None
        self.retry_count = 0
        self.resumable_uri = ""
        self.resumable_progress = 0


if __name__ == "__main__":
    unittest.main()
