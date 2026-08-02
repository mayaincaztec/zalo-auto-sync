"""
Unit Tests for DatabaseManager
"""

import os
import sqlite3
import tempfile
import unittest
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus


class TestDatabaseManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_db.db")
        self.db = DatabaseManager(self.db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        try:
            os.rmdir(self.test_dir)
        except OSError:
            pass

    def test_add_and_get_item(self):
        item = DownloadItem(
            filename="baocao.pdf",
            filepath="/tmp/baocao.pdf",
            filesize=102400,
            status=SyncStatus.PENDING,
            hash="a1b2c3d4e5f67890"
        )
        item_id = self.db.add_item(item)
        self.assertGreater(item_id, 0)

        retrieved = self.db.get_item_by_hash("a1b2c3d4e5f67890")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.filename, "baocao.pdf")

    def test_update_status_and_stats(self):
        item = DownloadItem(
            filename="anh.png",
            filepath="/tmp/anh.png",
            filesize=500000,
            group_name="Team Alpha",
            file_id="zf_001",
            download_status="downloaded",
            status=SyncStatus.PENDING,
            hash="hash_12345"
        )
        item_id = self.db.add_item(item)

        self.db.update_status(item_id, SyncStatus.COMPLETED, drive_file_id="drive_file_99")
        self.assertTrue(self.db.is_file_uploaded("hash_12345"))
        self.assertTrue(self.db.is_file_processed("zf_001", "Team Alpha"))

        stats = self.db.get_stats()
        self.assertEqual(stats["uploaded_files"], 1)
        self.assertEqual(stats["total_bytes"], 500000)

    def test_get_processed_file_ids_batch(self):
        self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            group_name="G1", file_id="f1", status=SyncStatus.COMPLETED
        ))
        self.db.add_item(DownloadItem(
            filename="b.pdf", filepath="/b.pdf", filesize=10,
            group_name="G1", file_id="f2", status=SyncStatus.FAILED
        ))
        self.db.add_item(DownloadItem(
            filename="c.pdf", filepath="/c.pdf", filesize=10,
            group_name="G2", file_id="f3", status=SyncStatus.PENDING
        ))
        processed_g1 = self.db.get_processed_file_ids("G1")
        self.assertIn("f1", processed_g1)
        self.assertNotIn("f2", processed_g1)
        self.assertEqual(self.db.get_processed_file_ids(), {"f1", "f3"})

    def test_resumable_state_roundtrip(self):
        item_id = self.db.add_item(DownloadItem(
            filename="big.zip", filepath="/big.zip", filesize=1000,
            group_name="G1", file_id="fresume", status=SyncStatus.UPLOADING
        ))
        self.assertTrue(self.db.set_resumable_state(item_id, "https://session/uri", 512))
        retrieved = self.db.get_item_by_hash.__self__  # noop guard
        row = self.db.get_all_items(limit=10)[0]
        self.assertEqual(row.resumable_uri, "https://session/uri")
        self.assertEqual(row.resumable_progress, 512)

    def test_get_resumable_state_returns_uri(self):
        item_id = self.db.add_item(DownloadItem(
            filename="big.zip", filepath="/big.zip", filesize=1000,
            group_name="G1", file_id="fresume2", status=SyncStatus.UPLOADING
        ))
        self.db.set_resumable_state(item_id, "https://session/abc", 300)
        uri, progress = self.db.get_resumable_state("fresume2", "G1")
        self.assertEqual(uri, "https://session/abc")
        self.assertEqual(progress, 300)

    def test_get_resumable_state_empty_when_unknown(self):
        uri, progress = self.db.get_resumable_state("missing", "G1")
        self.assertEqual((uri, progress), ("", 0))

    def test_clear_resumable_state(self):
        item_id = self.db.add_item(DownloadItem(
            filename="big.zip", filepath="/big.zip", filesize=1000,
            group_name="G1", file_id="fresume3", status=SyncStatus.UPLOADING
        ))
        self.db.set_resumable_state(item_id, "https://session/xyz", 900)
        self.assertTrue(self.db.clear_resumable_state(item_id))
        row = self.db.get_all_items(limit=10)[0]
        self.assertEqual(row.resumable_uri, "")
        self.assertEqual(row.resumable_progress, 0)
        uri, progress = self.db.get_resumable_state("fresume3", "G1")
        self.assertEqual((uri, progress), ("", 0))

    def test_get_resumable_state_latest_row_wins(self):
        self.db.add_item(DownloadItem(
            filename="a.zip", filepath="/a.zip", filesize=1000,
            group_name="G1", file_id="fmulti", status=SyncStatus.FAILED
        ))
        first_id = self.db.get_all_items(limit=10)[0].id
        self.db.set_resumable_state(first_id, "https://old", 10)
        self.db.add_item(DownloadItem(
            filename="b.zip", filepath="/b.zip", filesize=1000,
            group_name="G1", file_id="fmulti", status=SyncStatus.FAILED
        ))
        second_id = self.db.get_all_items(limit=10)[0].id
        self.db.set_resumable_state(second_id, "https://new", 800)
        uri, progress = self.db.get_resumable_state("fmulti", "G1")
        self.assertEqual(uri, "https://new")
        self.assertEqual(progress, 800)

    def test_is_file_processed_empty_id_returns_false(self):
        self.assertFalse(self.db.is_file_processed(""))
        self.assertFalse(self.db.is_file_processed("", "G1"))

    def test_is_file_processed_without_group(self):
        self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            file_id="f_nogroup", status=SyncStatus.PENDING
        ))
        self.assertTrue(self.db.is_file_processed("f_nogroup"))
        self.assertTrue(self.db.is_file_processed("f_nogroup", ""))

    def test_filter_unprocessed_without_group(self):
        self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            file_id="f1", status=SyncStatus.COMPLETED
        ))
        self.db.add_item(DownloadItem(
            filename="b.pdf", filepath="/b.pdf", filesize=10,
            file_id="f2", status=SyncStatus.FAILED
        ))
        remaining = self.db.filter_unprocessed("", ["f1", "f2", "f3"])
        self.assertEqual(remaining, ["f2", "f3"])

    def test_filter_unprocessed_with_group(self):
        self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            group_name="G1", file_id="g1f1", status=SyncStatus.COMPLETED
        ))
        self.db.add_item(DownloadItem(
            filename="b.pdf", filepath="/b.pdf", filesize=10,
            group_name="G2", file_id="g2f1", status=SyncStatus.COMPLETED
        ))
        remaining = self.db.filter_unprocessed("G1", ["g1f1", "g2f1", "g1f2"])
        self.assertEqual(remaining, ["g2f1", "g1f2"])

    def test_filter_unprocessed_empty_input(self):
        self.assertEqual(self.db.filter_unprocessed("G1", []), [])
        self.assertEqual(self.db.filter_unprocessed("G1", ["", None]), [])

    def test_increment_retry(self):
        item_id = self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            file_id="fretry", status=SyncStatus.FAILED
        ))
        self.assertEqual(self.db.increment_retry(item_id), 1)
        self.assertEqual(self.db.increment_retry(item_id), 2)

    def test_increment_retry_missing_id(self):
        self.assertEqual(self.db.increment_retry(99999), 0)

    def test_update_status_with_explicit_uploaded_time(self):
        item_id = self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            file_id="ftime", status=SyncStatus.PENDING
        ))
        self.db.update_status(
            item_id, SyncStatus.COMPLETED,
            drive_file_id="did1", uploaded_time="2024-01-01 00:00:00"
        )
        row = self.db.get_all_items(limit=10)[0]
        self.assertEqual(row.uploaded_time, "2024-01-01 00:00:00")

    def test_update_status_skipped(self):
        item_id = self.db.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            file_id="fskip", status=SyncStatus.PENDING
        ))
        self.db.update_status(item_id, SyncStatus.SKIPPED)
        row = self.db.get_all_items(limit=10)[0]
        self.assertEqual(row.status, SyncStatus.SKIPPED)

    def test_get_resumable_state_no_group_name(self):
        item_id = self.db.add_item(DownloadItem(
            filename="a.zip", filepath="/a.zip", filesize=1000,
            file_id="fresume_nogroup", status=SyncStatus.FAILED
        ))
        self.db.set_resumable_state(item_id, "https://session/nogroup", 77)
        uri, progress = self.db.get_resumable_state("fresume_nogroup")
        self.assertEqual(uri, "https://session/nogroup")
        self.assertEqual(progress, 77)

    def test_get_resumable_state_empty_file_id(self):
        self.assertEqual(self.db.get_resumable_state(""), ("", 0))

    def test_legacy_schema_gets_migrated(self):
        # Simulate a pre-migration database missing the newer columns
        legacy_path = os.path.join(self.test_dir, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("""
            CREATE TABLE download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                filepath TEXT DEFAULT '',
                filesize INTEGER NOT NULL DEFAULT 0,
                created_time TEXT NOT NULL,
                uploaded_time TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                hash TEXT DEFAULT '',
                drive_file_id TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0
            );
        """)
        conn.commit()
        conn.close()

        migrated = DatabaseManager(legacy_path)
        migrated.add_item(DownloadItem(
            filename="a.pdf", filepath="/a.pdf", filesize=10,
            group_name="G1", file_id="f_legacy", status=SyncStatus.PENDING
        ))
        row = migrated.get_all_items(limit=10)[0]
        self.assertEqual(row.group_name, "G1")
        self.assertEqual(row.resumable_uri, "")
        migrated.close()


if __name__ == "__main__":
    unittest.main()
