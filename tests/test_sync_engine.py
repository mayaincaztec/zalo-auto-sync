"""Tests for the local-only Zalo group download engine."""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.core.sync_engine import (
    ZaloGroupSyncEngine,
    resolve_local_destination,
)
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.zalo_controller import GroupFile


class FakeDateTime:
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


class TestLocalDestination(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_returns_original_name_when_available(self):
        result = resolve_local_destination(self.folder, "report.pdf", "rename")
        self.assertEqual(result, os.path.join(self.folder, "report.pdf"))

    def test_rename_adds_incrementing_suffix(self):
        open(os.path.join(self.folder, "report.pdf"), "wb").close()
        open(os.path.join(self.folder, "report (1).pdf"), "wb").close()
        result = resolve_local_destination(self.folder, "report.pdf", "rename")
        self.assertEqual(result, os.path.join(self.folder, "report (2).pdf"))

    def test_skip_returns_none_for_existing_name(self):
        open(os.path.join(self.folder, "report.pdf"), "wb").close()
        self.assertIsNone(resolve_local_destination(self.folder, "report.pdf", "skip"))

    def test_overwrite_reuses_existing_path(self):
        path = os.path.join(self.folder, "report.pdf")
        open(path, "wb").close()
        self.assertEqual(resolve_local_destination(self.folder, "report.pdf", "overwrite"), path)

    def test_filename_is_confined_to_destination_folder(self):
        result = resolve_local_destination(self.folder, "../outside.pdf", "rename")
        self.assertEqual(result, os.path.join(self.folder, "outside.pdf"))


class TestSyncEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.download_dir = os.path.join(self.test_dir, "sharepoint")
        ConfigManager._instance = None
        self.config = ConfigManager(os.path.join(self.test_dir, "config.json"))
        self.config.update_all({
            "group_name": "LOIMINH",
            "group_names": ["LOIMINH"],
            "auto_schedule_mode": "interval",
            "auto_interval_hours": 1,
            "check_interval": 3600,
            "download_folder": self.download_dir,
            "download_timeout": 30,
            "duplicate_action": "rename",
        })

        self.db = DatabaseManager(os.path.join(self.test_dir, "test.db"))
        self.logs = []
        self.items = []
        self.zc = MagicMock()
        self.engine = ZaloGroupSyncEngine(
            config_manager=self.config,
            db_manager=self.db,
            log_callback=lambda level, message: self.logs.append((level, message)),
            item_callback=lambda item, message, percent: self.items.append((item, message, percent)),
            zalo_controller=self.zc,
        )

        self.sample_file = os.path.join(self.test_dir, "sample.pdf")
        with open(self.sample_file, "wb") as handle:
            handle.write(b"sample-content-for-hash")

    def tearDown(self):
        self.engine.stop()
        self.db.close()
        ConfigManager._instance = None
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _has_log(self, needle):
        return any(needle in message for _, message in self.logs)

    def test_init_wires_local_dependencies(self):
        self.assertIs(self.engine.config_manager, self.config)
        self.assertIs(self.engine.db_manager, self.db)
        self.assertIs(self.engine.zalo_controller, self.zc)
        self.assertFalse(self.engine._owns_controller)
        self.assertFalse(self.engine.is_running)

    def test_owned_controller_uses_engine_callbacks(self):
        with patch("zalo_drive_sync.core.sync_engine.ZaloController") as controller_cls:
            engine = ZaloGroupSyncEngine(self.config, self.db)
        kwargs = controller_cls.call_args.kwargs
        self.assertEqual(kwargs["log_callback"], engine.log)
        self.assertIs(kwargs["config_manager"], self.config)

    def test_start_is_idempotent_and_stop_aborts_waiting(self):
        with patch.object(self.engine, "run_single_scan"):
            self.engine.start()
            thread = self.engine._thread
            self.engine.start()
            self.assertIs(self.engine._thread, thread)
            self.engine.stop()
        self.assertFalse(self.engine.is_running)
        self.zc.abort_waiting.assert_called_once()
        self.zc._stop_bridge.assert_not_called()

    def test_status_callback_alias_forwards(self):
        item = DownloadItem(id=1, filename="x.pdf")
        self.engine.on_queue_status_update(item, "Đã tải xuống", 100)
        self.assertEqual(self.items, [(item, "Đã tải xuống", 100)])

    def test_schedule_disabled_always_in_window(self):
        self.config.set("schedule_enabled", False)
        self.assertTrue(self.engine._in_schedule_window())

    def test_schedule_within_and_outside_window(self):
        self.config.update_all({"schedule_enabled": True, "schedule_start": "08:00", "schedule_end": "10:00"})
        for hour, expected in ((9, True), (12, False)):
            FakeDateTime.fixed = datetime(2026, 1, 1, hour, 0)
            with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
                self.assertEqual(self.engine._in_schedule_window(), expected)

    def test_schedule_cross_midnight(self):
        self.config.update_all({"schedule_enabled": True, "schedule_start": "22:00", "schedule_end": "06:00"})
        for hour, expected in ((23, True), (3, True), (12, False)):
            FakeDateTime.fixed = datetime(2026, 1, 1, hour, 0)
            with patch("zalo_drive_sync.core.sync_engine.datetime", FakeDateTime):
                self.assertEqual(self.engine._in_schedule_window(), expected)

    def test_run_single_scan_requires_group(self):
        self.config.update_all({"group_name": "", "group_names": []})
        self.engine.run_single_scan()
        self.zc.ensure_zalo_running.assert_not_called()
        self.assertTrue(self._has_log("No Zalo groups"))

    def test_run_single_scan_requires_download_folder(self):
        self.config.set("download_folder", "")
        self.engine.run_single_scan()
        self.zc.ensure_zalo_running.assert_not_called()
        self.assertTrue(self._has_log("No local download folder"))

    def test_run_single_scan_stops_when_zalo_unavailable(self):
        self.zc.ensure_zalo_running.return_value = False
        self.engine.run_single_scan()
        self.zc.open_group.assert_not_called()
        self.assertTrue(self._has_log("Could not connect"))

    def test_run_single_scan_delegates_without_google_drive(self):
        self.zc.ensure_zalo_running.return_value = True
        with patch.object(self.engine, "_scan_single_group") as scan:
            self.engine.run_single_scan()
        scan.assert_called_once_with("LOIMINH", self.download_dir, 30)

    def test_run_single_scan_scans_all_selected_groups(self):
        self.config.set("group_names", ["Nhóm A", "Nhóm B", "Nhóm C"])
        self.zc.ensure_zalo_running.return_value = True
        with patch.object(self.engine, "_scan_single_group") as scan:
            self.engine.run_single_scan()
        self.zc.ensure_zalo_running.assert_called_once()
        self.assertEqual(
            [call.args[0] for call in scan.call_args_list],
            ["Nhóm A", "Nhóm B", "Nhóm C"],
        )

    def test_seconds_until_next_daily_run_same_day(self):
        self.config.update_all({"auto_schedule_mode": "daily", "daily_times": ["09:00", "18:00"]})
        now = datetime(2026, 1, 1, 8, 30)
        self.assertEqual(self.engine._seconds_until_next_daily_run(now), 30 * 60)

    def test_seconds_until_next_daily_run_rolls_to_tomorrow(self):
        self.config.update_all({"auto_schedule_mode": "daily", "daily_times": ["09:00", "18:00"]})
        now = datetime(2026, 1, 1, 19, 0)
        self.assertEqual(self.engine._seconds_until_next_daily_run(now), 14 * 60 * 60)

    def test_scan_open_group_failure(self):
        self.zc.open_group.return_value = False
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.assertTrue(self._has_log("Failed to open group"))

    def test_scan_no_files(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = []
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.assertTrue(self._has_log("No files found"))

    def test_scan_download_failure_is_recorded(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = None
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        item = self.db.get_all_items(1)[0]
        self.assertEqual(item.status, SyncStatus.FAILED)
        self.assertEqual(item.download_status, "failed")
        self.assertEqual(item.drive_status, "not_required")
        self.assertEqual(self.items[0][1:], ("Tải xuống thất bại", 0))

    def test_scan_success_completes_locally(self):
        group_file = make_group_file(fid="f9", name="report.pdf")
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [group_file]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)

        call = self.zc.download_group_file.call_args.kwargs
        self.assertEqual(call["destination_path"], os.path.join(self.download_dir, "report.pdf"))
        item = self.db.get_all_items(1)[0]
        self.assertEqual(item.status, SyncStatus.COMPLETED)
        self.assertEqual(item.download_status, "downloaded")
        self.assertEqual(item.drive_status, "not_required")
        self.assertEqual(item.filepath, self.sample_file)
        self.assertEqual(self.items[0][1:], ("Đã tải xuống", 100))

    def test_scan_existing_name_skip_policy(self):
        os.makedirs(self.download_dir)
        existing = os.path.join(self.download_dir, "report.pdf")
        with open(existing, "wb") as handle:
            handle.write(b"old")
        self.config.set("duplicate_action", "skip")
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(name="report.pdf")]
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.zc.download_group_file.assert_not_called()
        item = self.db.get_all_items(1)[0]
        self.assertEqual(item.status, SyncStatus.SKIPPED)
        self.assertEqual(item.filepath, existing)

    def test_scan_existing_name_rename_policy(self):
        os.makedirs(self.download_dir)
        open(os.path.join(self.download_dir, "report.pdf"), "wb").close()
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(name="report.pdf")]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        destination = self.zc.download_group_file.call_args.kwargs["destination_path"]
        self.assertEqual(destination, os.path.join(self.download_dir, "report (1).pdf"))

    def test_scan_same_hash_still_records_downloaded_attachment(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file()]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        with patch.object(self.db, "is_file_downloaded", return_value=True):
            self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.assertEqual(self.db.get_all_items(1)[0].status, SyncStatus.COMPLETED)
        self.assertIn("nội dung trùng", self.items[0][1])

    def test_scan_hash_failure_uses_file_id_fallback(self):
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [make_group_file(fid="fallback")]
        self.zc.download_group_file.return_value = self.sample_file
        self.engine.is_running = True
        with patch("zalo_drive_sync.core.sync_engine.calculate_sha256", side_effect=OSError("read")):
            self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.assertEqual(self.db.get_all_items(1)[0].hash, "hash_fallback")

    def test_processed_file_is_not_downloaded_again(self):
        group_file = make_group_file(fid="known")
        self.db.add_item(DownloadItem(
            filename=group_file.filename,
            group_name="LOIMINH",
            file_id="known",
            download_status="downloaded",
            status=SyncStatus.COMPLETED,
            hash="existing",
        ))
        self.zc.open_group.return_value = True
        self.zc.scan_group_files.return_value = [group_file]
        self.engine.is_running = True
        self.engine._scan_single_group("LOIMINH", self.download_dir, 30)
        self.zc.download_group_file.assert_not_called()
        self.assertTrue(self._has_log("already processed"))

    def test_sync_loop_logs_scan_exception(self):
        with patch.object(self.engine, "run_single_scan", side_effect=RuntimeError("boom")):
            self.engine.start()
            time.sleep(0.05)
            self.engine.stop()
        self.assertTrue(self._has_log("Error during group scan"))


if __name__ == "__main__":
    unittest.main()
