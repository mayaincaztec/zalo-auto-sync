"""
Unit Tests for Hasher
"""

import os
import tempfile
import unittest
from zalo_drive_sync.core.hasher import calculate_sha256


class TestHasher(unittest.TestCase):

    def setUp(self):
        self.test_file = tempfile.NamedTemporaryFile(delete=False)
        self.test_file.write(b"Hello Zalo PC Sync to Google Drive!")
        self.test_file.close()

    def tearDown(self):
        if os.path.exists(self.test_file.name):
            os.remove(self.test_file.name)

    def test_sha256_calculation(self):
        h1 = calculate_sha256(self.test_file.name)
        self.assertIsInstance(h1, str)
        self.assertEqual(len(h1), 64)

        # Same content should yield identical hash
        h2 = calculate_sha256(self.test_file.name)
        self.assertEqual(h1, h2)

    def test_sha256_multiple_chunks(self):
        # Large content forces multiple read chunks (default 64KB)
        big = tempfile.NamedTemporaryFile(delete=False)
        big.write(b"x" * (65536 * 3 + 123))
        big.close()
        try:
            h = calculate_sha256(big.name, chunk_size=65536)
            self.assertEqual(len(h), 64)
        finally:
            os.remove(big.name)

    def test_sha256_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            calculate_sha256(os.path.join(tempfile.gettempdir(), "does_not_exist.pdf"))


if __name__ == "__main__":
    unittest.main()
