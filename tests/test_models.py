"""
Unit Tests for Database Models
"""

import unittest
from zalo_drive_sync.database.models import DownloadItem, SyncStatus


class TestDownloadItem(unittest.TestCase):

    def test_defaults(self):
        item = DownloadItem()
        self.assertIsNone(item.id)
        self.assertEqual(item.filename, "")
        self.assertEqual(item.status, SyncStatus.PENDING)
        self.assertEqual(item.retry_count, 0)
        self.assertEqual(item.resumable_uri, "")
        self.assertEqual(item.resumable_progress, 0)
        self.assertIsNone(item.drive_file_id)
        self.assertIsNone(item.error_message)

    def test_to_dict_includes_all_fields(self):
        item = DownloadItem(
            id=5,
            filename="a.pdf",
            filepath="/a.pdf",
            filesize=100,
            group_name="G1",
            message_id="m1",
            file_id="f1",
            download_status="downloaded",
            drive_status="completed",
            status=SyncStatus.COMPLETED,
            hash="h1",
            drive_file_id="d1",
            error_message=None,
            retry_count=2,
            resumable_uri="https://session/x",
            resumable_progress=42,
        )
        d = item.to_dict()
        self.assertEqual(d["id"], 5)
        self.assertEqual(d["filename"], "a.pdf")
        self.assertEqual(d["filepath"], "/a.pdf")
        self.assertEqual(d["filesize"], 100)
        self.assertEqual(d["group_name"], "G1")
        self.assertEqual(d["message_id"], "m1")
        self.assertEqual(d["file_id"], "f1")
        self.assertEqual(d["download_status"], "downloaded")
        self.assertEqual(d["drive_status"], "completed")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["hash"], "h1")
        self.assertEqual(d["drive_file_id"], "d1")
        self.assertEqual(d["retry_count"], 2)
        self.assertEqual(d["resumable_uri"], "https://session/x")
        self.assertEqual(d["resumable_progress"], 42)
        self.assertEqual(len(d), 19)

    def test_to_dict_status_as_string_when_not_enum(self):
        item = DownloadItem(status="queued")
        self.assertEqual(item.to_dict()["status"], "queued")

    def test_sync_status_values(self):
        self.assertEqual(SyncStatus.PENDING.value, "pending")
        self.assertEqual(SyncStatus.QUEUED.value, "queued")
        self.assertEqual(SyncStatus.UPLOADING.value, "uploading")
        self.assertEqual(SyncStatus.COMPLETED.value, "completed")
        self.assertEqual(SyncStatus.FAILED.value, "failed")
        self.assertEqual(SyncStatus.SKIPPED.value, "skipped")


if __name__ == "__main__":
    unittest.main()
