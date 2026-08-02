"""
Unit Tests for zalo_service helpers
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from zalo_drive_sync.services.zalo_service import (
    get_default_zalo_folder,
    wait_for_file_stability,
)


class TestGetDefaultZaloFolder(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()

    def tearDown(self):
        for root, _, files in os.walk(self.home, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            os.rmdir(root)

    def _patch_home(self):
        return patch("os.path.expanduser", return_value=self.home)

    def test_returns_documents_dir_first(self):
        docs = os.path.join(self.home, "Documents", "Zalo Received Files")
        os.makedirs(docs)
        with self._patch_home():
            self.assertEqual(get_default_zalo_folder(), docs)

    def test_returns_downloads_dir_when_documents_missing(self):
        dl = os.path.join(self.home, "Downloads", "Zalo Received Files")
        os.makedirs(dl)
        with self._patch_home():
            self.assertEqual(get_default_zalo_folder(), dl)

    def test_returns_plain_downloads_fallback(self):
        dl = os.path.join(self.home, "Downloads")
        os.makedirs(dl)
        with self._patch_home():
            self.assertEqual(get_default_zalo_folder(), dl)

    def test_creates_default_dir_when_none_exist(self):
        expected = os.path.join(self.home, "Documents", "Zalo Received Files")
        with self._patch_home():
            result = get_default_zalo_folder()
        self.assertEqual(result, expected)
        self.assertTrue(os.path.exists(expected))


class TestWaitForFileStability(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.filepath = os.path.join(self.dir, "sample.pdf")
        with open(self.filepath, "wb") as f:
            f.write(b"x" * 100)

    def tearDown(self):
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
        os.rmdir(self.dir)

    def test_missing_file_returns_false(self):
        missing = os.path.join(self.dir, "nope.pdf")
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            self.assertFalse(wait_for_file_stability(missing, 0.01, 1.0))

    def test_stable_file_returns_true(self):
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            self.assertTrue(wait_for_file_stability(self.filepath, 0.01, 5.0))

    def test_empty_file_never_stable(self):
        empty = os.path.join(self.dir, "empty.pdf")
        open(empty, "wb").close()
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            self.assertFalse(wait_for_file_stability(empty, 0.01, 0.05))
        os.remove(empty)

    def test_growing_file_times_out(self):
        import itertools
        counter = itertools.count(100, 50)
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch(
                "zalo_drive_sync.services.zalo_service.os.path.getsize",
                side_effect=lambda p: next(counter),
            ):
                self.assertFalse(wait_for_file_stability(self.filepath, 0.01, 0.05))

    def test_growing_then_stable_returns_true(self):
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch(
                "zalo_drive_sync.services.zalo_service.os.path.getsize",
                side_effect=[100, 200, 200, 200],
            ):
                self.assertTrue(wait_for_file_stability(self.filepath, 0.01, 5.0))

    def test_permission_error_retries_and_times_out(self):
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch(
                "zalo_drive_sync.services.zalo_service.os.path.getsize",
                side_effect=PermissionError("locked"),
            ):
                self.assertFalse(wait_for_file_stability(self.filepath, 0.01, 0.05))

    def test_permission_error_then_success(self):
        real_getsize = os.path.getsize
        sizes = iter([100, PermissionError("locked"), 200, 200])

        def flaky_getsize(p):
            v = next(sizes)
            if isinstance(v, Exception):
                raise v
            return v

        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_service.os.path.getsize", side_effect=flaky_getsize):
                self.assertTrue(wait_for_file_stability(self.filepath, 0.01, 5.0))

    def test_open_read_lock_failure_times_out(self):
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_service.open", side_effect=PermissionError("locked")):
                self.assertFalse(wait_for_file_stability(self.filepath, 0.01, 0.05))

    def test_oserror_during_read_times_out(self):
        with patch("zalo_drive_sync.services.zalo_service.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_service.os.path.getsize", side_effect=OSError("io")):
                self.assertFalse(wait_for_file_stability(self.filepath, 0.01, 0.05))


if __name__ == "__main__":
    unittest.main()
