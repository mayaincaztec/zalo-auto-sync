"""
Unit Tests for UploadQueueManager and UploadTask
"""

import os
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from zalo_drive_sync.core.upload_queue import UploadQueueManager, UploadTask
from zalo_drive_sync.database.models import DownloadItem, SyncStatus


_MADE_FILES = []


def make_item(filename="doc.pdf", filepath="", filesize=100):
    if not filepath:
        filepath = os.path.join(tempfile.gettempdir(), filename)
        if not os.path.exists(filepath):
            with open(filepath, "wb") as f:
                f.write(b"x" * filesize)
        _MADE_FILES.append(filepath)
    return DownloadItem(
        id=1,
        filename=filename,
        filepath=filepath,
        filesize=filesize,
        status=SyncStatus.PENDING,
        hash="hash_abc"
    )


class TestUploadTask(unittest.TestCase):

    def test_task_stores_fields(self):
        item = make_item()
        task = UploadTask(item, "folder_123", "rename")
        self.assertIs(task.item, item)
        self.assertEqual(task.gdrive_folder_id, "folder_123")
        self.assertEqual(task.duplicate_action, "rename")

    def test_task_defaults(self):
        task = UploadTask(make_item(), "folder_123")
        self.assertEqual(task.duplicate_action, "rename")


class TestUploadQueueManager(unittest.TestCase):

    def setUp(self):
        self.db = MagicMock()
        self.gdrive = MagicMock()
        self.logs = []
        self.statuses = []
        self.qm = UploadQueueManager(
            db_manager=self.db,
            gdrive_service=self.gdrive,
            max_workers=1,
            max_retries=2,
            status_callback=lambda item, msg, pct: self.statuses.append((item, msg, pct)),
            log_callback=lambda lvl, msg: self.logs.append((lvl, msg))
        )

    def tearDown(self):
        if self.qm.is_running:
            self.qm.stop()

    # --- Lifecycle ---

    def test_start_sets_running_and_starts_workers(self):
        self.qm.start()
        self.assertTrue(self.qm.is_running)
        self.assertIsNotNone(self.qm.executor)
        self.assertTrue(any("started" in m for _, m in self.logs))

    def test_log_without_callback_is_noop(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive)
        qm.log("INFO", "nobody listens")  # must not raise

    def test_add_item_without_callback_still_queues(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive)
        qm.add_item(make_item(), "fld")
        self.assertEqual(qm.task_queue.qsize(), 1)

    def test_start_is_idempotent(self):
        self.qm.start()
        executor1 = self.qm.executor
        self.qm.start()
        self.assertIs(self.qm.executor, executor1)

    def test_stop_when_not_running_is_noop(self):
        self.qm.stop()
        self.assertFalse(self.qm.is_running)
        self.assertIsNone(self.qm.executor)

    def test_stop_stops_workers(self):
        self.qm.start()
        self.qm.stop()
        self.assertFalse(self.qm.is_running)
        self.assertIsNone(self.qm.executor)
        self.assertTrue(any("stopped" in m for _, m in self.logs))

    # --- add_item ---

    def test_add_item_marks_queued_and_puts_task(self):
        item = make_item()
        self.qm.add_item(item, "folder_1", "skip")
        self.db.update_status.assert_called_once_with(item.id, SyncStatus.QUEUED)
        self.assertEqual(item.status, SyncStatus.QUEUED)
        self.assertEqual(self.qm.task_queue.qsize(), 1)
        # status callback fired with "In Queue"
        self.assertTrue(any(s[1] == "In Queue" for s in self.statuses))

    # --- _process_upload success ---

    def test_upload_success_marks_completed(self):
        self.gdrive.upload_file.return_value = {"id": "drive_1", "name": "doc.pdf", "status": "completed"}
        item = make_item()
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(item, "fld", "rename"))
        self.assertEqual(item.status, SyncStatus.COMPLETED)
        self.assertEqual(item.drive_file_id, "drive_1")
        self.db.update_status.assert_called()
        calls = [c[0] for c in self.db.update_status.call_args_list]
        self.assertTrue(any(SyncStatus.UPLOADING in c for c in calls))
        self.assertTrue(any(SyncStatus.COMPLETED in c for c in calls))
        self.assertTrue(any(s[1] == "Completed" for s in self.statuses))

    def test_upload_success_fires_progress_callback(self):
        self.gdrive.upload_file.side_effect = lambda **kw: kw.get("progress_callback")(50, 100)
        # simulate upload_file calling progress then returning result
        self.gdrive.upload_file.side_effect = None
        def fake_upload(**kwargs):
            if kwargs.get("progress_callback"):
                kwargs["progress_callback"](50, 100)
                kwargs["progress_callback"](100, 100)
            return {"id": "d1", "status": "completed"}
        self.gdrive.upload_file.side_effect = fake_upload
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertTrue(any("Uploading (50%)" in s[1] for s in self.statuses))
        self.assertTrue(any("Uploading (100%)" in s[1] for s in self.statuses))

    def test_upload_progress_skips_zero_total(self):
        # progress with total_bytes=0 must not raise or emit status
        calls = []
        self.qm.status_callback = lambda item, msg, pct: calls.append(msg)
        self.gdrive.upload_file.side_effect = lambda **kw: kw["progress_callback"](0, 0) or {"id": "d", "status": "completed"}
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertNotIn("Uploading (0%)", calls)

    def test_upload_progress_skips_same_percent(self):
        calls = []
        self.qm.status_callback = lambda item, msg, pct: calls.append(msg)

        def fake_upload(**kwargs):
            if kwargs.get("progress_callback"):
                kwargs["progress_callback"](50, 100)
                kwargs["progress_callback"](50, 100)  # unchanged -> suppressed
            return {"id": "d", "status": "completed"}

        self.gdrive.upload_file.side_effect = fake_upload
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(calls.count("Uploading (50%)"), 1)

    def test_upload_missing_file_marks_failed(self):
        item = DownloadItem(
            id=2, filename="ghost.pdf", filepath="", filesize=10,
            status=SyncStatus.PENDING, hash="h1"
        )
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.FAILED)
        self.assertTrue(any(s[1] == "Failed: file not found" for s in self.statuses))
        self.gdrive.upload_file.assert_not_called()

    def test_upload_missing_file_without_status_callback(self):
        item = DownloadItem(
            id=2, filename="ghost.pdf", filepath="", filesize=10,
            status=SyncStatus.PENDING, hash="h1"
        )
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive)
        qm.is_running = True
        qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.FAILED)

    def test_upload_without_status_callback(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive)
        qm.is_running = True

        def fake_upload(**kwargs):
            if kwargs.get("progress_callback"):
                kwargs["progress_callback"](50, 100)
            return {"id": "d1", "status": "completed"}

        self.gdrive.upload_file.side_effect = fake_upload
        qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(self.gdrive.upload_file.call_count, 1)

    def test_upload_skipped_without_status_callback(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive)
        qm.is_running = True
        self.gdrive.upload_file.return_value = {"id": "x", "status": "skipped"}
        qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(self.gdrive.upload_file.call_count, 1)

    def test_upload_failure_without_status_callback(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive, max_retries=0)
        qm.is_running = True
        self.gdrive.upload_file.side_effect = Exception("boom")
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(qm.task_queue.qsize(), 0)

    # --- _process_upload skipped ---

    def test_upload_skipped_marks_skipped(self):
        self.gdrive.upload_file.return_value = {"id": "existing", "name": "doc.pdf", "status": "skipped"}
        item = make_item()
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(item, "fld", "skip"))
        self.assertEqual(item.status, SyncStatus.SKIPPED)
        self.db.update_status.assert_called()
        last_call = self.db.update_status.call_args_list[-1][0]
        self.assertEqual(last_call[1], SyncStatus.SKIPPED)
        self.assertTrue(any(s[1] == "Skipped" for s in self.statuses))

    # --- _process_upload failure / retries ---

    def test_upload_failure_retries_then_succeeds(self):
        self.gdrive.upload_file.side_effect = [Exception("network"), {"id": "d1", "status": "completed"}]
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            item = make_item()
            self.qm.is_running = True
            self.qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.COMPLETED)
        self.assertEqual(self.gdrive.upload_file.call_count, 2)
        self.db.increment_retry.assert_called_once_with(item.id)

    def test_upload_resumes_from_saved_uri_on_retry(self):
        # First attempt fails after persisting a resumable session; the retry
        # must pass the saved URI/progress back to upload_file.
        self.db.set_resumable_state = MagicMock()
        self.db.clear_resumable_state = MagicMock()

        def fake_upload(**kwargs):
            resume_cb = kwargs.get("resume_callback")
            if kwargs.get("resumable_uri"):
                return {"id": "d1", "status": "completed"}
            # simulate first attempt: fail, but first persist 60% progress
            if resume_cb:
                resume_cb("https://session/abc", 60)
            raise Exception("network")

        self.gdrive.upload_file.side_effect = fake_upload
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            item = make_item()
            self.qm.is_running = True
            self.qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.COMPLETED)
        self.assertEqual(self.gdrive.upload_file.call_count, 2)
        first_call = self.gdrive.upload_file.call_args_list[0][1]
        second_call = self.gdrive.upload_file.call_args_list[1][1]
        self.assertIsNone(first_call["resumable_uri"])
        self.assertEqual(second_call["resumable_uri"], "https://session/abc")
        self.assertEqual(second_call["resumable_progress"], 60)
        self.db.set_resumable_state.assert_called()
        self.db.clear_resumable_state.assert_called_once()

    def test_upload_uses_saved_uri_from_item(self):
        # An item restored from DB with a saved session resumes immediately.
        item = make_item()
        item.resumable_uri = "https://session/saved"
        item.resumable_progress = 100
        self.gdrive.upload_file.return_value = {"id": "d1", "status": "completed"}
        self.qm.is_running = True
        self.qm._process_upload(UploadTask(item, "fld"))
        kwargs = self.gdrive.upload_file.call_args[1]
        self.assertEqual(kwargs["resumable_uri"], "https://session/saved")
        self.assertEqual(kwargs["resumable_progress"], 100)

    def test_upload_failed_clears_nothing_but_persists_session(self):
        self.db.set_resumable_state = MagicMock()
        self.db.clear_resumable_state = MagicMock()
        self.gdrive.upload_file.side_effect = Exception("boom")
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            item = make_item()
            self.qm.is_running = True
            self.qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.FAILED)
        self.db.clear_resumable_state.assert_not_called()

    def test_upload_failure_exhausts_retries_marks_failed(self):
        self.gdrive.upload_file.side_effect = Exception("boom")
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            item = make_item()
            self.qm.is_running = True
            self.qm._process_upload(UploadTask(item, "fld"))
        self.assertEqual(item.status, SyncStatus.FAILED)
        self.assertEqual(item.error_message, "boom")
        self.db.update_status.assert_called()
        last_call = self.db.update_status.call_args_list[-1][0]
        self.assertEqual(last_call[1], SyncStatus.FAILED)
        self.assertTrue(any("Failed: boom" in s[1] for s in self.statuses))
        self.assertEqual(self.db.increment_retry.call_count, 3)  # initial + 2 retries

    def test_upload_failure_no_retries(self):
        self.qm.max_retries = 0
        self.gdrive.upload_file.side_effect = Exception("x")
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            self.qm.is_running = True
            self.qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(self.gdrive.upload_file.call_count, 1)
        self.assertEqual(self.db.increment_retry.call_count, 1)

    def test_stop_flag_aborts_retry_loop(self):
        self.qm.is_running = True
        def raising(**kwargs):
            self.qm.is_running = False  # simulate stop() during first attempt
            raise Exception("stop requested")
        self.gdrive.upload_file.side_effect = raising
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            self.qm._process_upload(UploadTask(make_item(), "fld"))
        # Only 1 attempt; retry loop aborts because is_running turned False
        self.assertEqual(self.gdrive.upload_file.call_count, 1)
        self.assertEqual(self.db.increment_retry.call_count, 1)

    def test_exponential_backoff_wait_time(self):
        self.gdrive.upload_file.side_effect = Exception("e")
        waited = []
        with patch("zalo_drive_sync.core.upload_queue.time.sleep", side_effect=lambda s: waited.append(s)):
            self.qm.is_running = True
            self.qm.max_retries = 2
            self.qm._process_upload(UploadTask(make_item(), "fld"))
        # waits 2^1 and 2^2 = 2s, 4s
        self.assertEqual(waited, [2, 4])

    # --- _worker_loop ---

    def test_worker_loop_processes_task(self):
        self.gdrive.upload_file.return_value = {"id": "d", "status": "completed"}
        self.qm.start()
        self.qm.add_item(make_item(), "fld")
        self.qm.task_queue.join()
        self.qm.stop()
        self.assertEqual(self.gdrive.upload_file.call_count, 1)

    def test_worker_loop_survives_unexpected_error(self):
        # A status callback that raises propagates out of _process_upload into
        # the worker's generic handler without killing the queue.
        self.qm.status_callback = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("callback boom"))
        self.qm.start()
        self.qm.task_queue.put(UploadTask(make_item(), "fld"))
        self.qm.task_queue.join()
        self.qm.stop()
        self.assertTrue(any("Unexpected error" in m for _, m in self.logs))

    def test_worker_loop_waits_on_empty_queue(self):
        # Worker must block on queue.Empty (timeout path) without crashing.
        self.qm.start()
        time.sleep(1.5)
        self.qm.stop()
        self.assertTrue(self.qm.executor is None or not self.qm.is_running)

    def test_retry_without_status_callback(self):
        qm = UploadQueueManager(db_manager=self.db, gdrive_service=self.gdrive, max_retries=2)
        qm.is_running = True
        self.gdrive.upload_file.side_effect = Exception("boom")
        with patch("zalo_drive_sync.core.upload_queue.time.sleep"):
            qm._process_upload(UploadTask(make_item(), "fld"))
        self.assertEqual(self.gdrive.upload_file.call_count, 3)
        self.assertEqual(self.db.increment_retry.call_count, 3)

    def test_worker_loop_drain_empty_queue_is_noop(self):
        self.qm.start()
        self.qm.task_queue.put(UploadTask(make_item(), "fld"))
        self.qm.task_queue.join()
        self.qm.stop()
        self.assertEqual(self.gdrive.upload_file.call_count, 1)


if __name__ == "__main__":
    unittest.main()
