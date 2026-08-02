"""
Unit Tests for the Auto-update Module (utils.updater)
"""

import os
import tempfile
import unittest
from unittest.mock import patch, mock_open

from zalo_drive_sync.utils import updater


class TestVersionParsing(unittest.TestCase):

    def test_parse_simple(self):
        self.assertEqual(updater.parse_version("1.1.5"), (1, 1, 5))

    def test_parse_with_v_prefix(self):
        self.assertEqual(updater.parse_version("v1.2.0"), (1, 2, 0))

    def test_parse_leading_zeros(self):
        self.assertEqual(updater.parse_version("1.02.3"), (1, 2, 3))

    def test_parse_invalid_returns_zeros(self):
        self.assertEqual(updater.parse_version("not-a-version"), (0, 0, 0))

    def test_parse_empty(self):
        self.assertEqual(updater.parse_version(""), (0, 0, 0))

    def test_is_newer_major(self):
        self.assertTrue(updater.is_newer_version("2.0.0", "1.9.9"))

    def test_is_newer_minor(self):
        self.assertTrue(updater.is_newer_version("1.2.0", "1.1.9"))

    def test_is_newer_patch(self):
        self.assertTrue(updater.is_newer_version("1.1.10", "1.1.9"))

    def test_not_newer_equal(self):
        self.assertFalse(updater.is_newer_version("1.1.5", "1.1.5"))

    def test_not_newer_older(self):
        self.assertFalse(updater.is_newer_version("1.0.0", "1.1.5"))

    def test_get_current_version_matches_package(self):
        from zalo_drive_sync import __version__
        self.assertEqual(updater.get_current_version(), __version__)


class TestFeedCheck(unittest.TestCase):

    def test_check_for_update_empty_url(self):
        self.assertIsNone(updater.check_for_update("", "1.1.5"))

    def test_check_for_update_returns_info_when_newer(self):
        payload = {"version": "1.2.0", "download_url": "http://x/app.zip", "notes": "New"}
        with patch.object(updater, "_http_get_json", return_value=payload) as mock_get:
            info = updater.check_for_update("http://feed", "1.1.5")
            mock_get.assert_called_once()
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(info["download_url"], "http://x/app.zip")
        self.assertEqual(info["notes"], "New")

    def test_check_for_update_ignores_older(self):
        payload = {"version": "1.0.0"}
        with patch.object(updater, "_http_get_json", return_value=payload):
            self.assertIsNone(updater.check_for_update("http://feed", "1.1.5"))

    def test_check_for_update_ignores_bad_payload(self):
        with patch.object(updater, "_http_get_json", return_value=None):
            self.assertIsNone(updater.check_for_update("http://feed", "1.1.5"))

    def test_check_for_update_ignores_missing_version(self):
        with patch.object(updater, "_http_get_json", return_value={"notes": "x"}):
            self.assertIsNone(updater.check_for_update("http://feed", "1.1.5"))

    def test_check_github_release_requires_repo(self):
        self.assertIsNone(updater.check_github_release("", "1.1.5"))
        self.assertIsNone(updater.check_github_release("novalueslash", "1.1.5"))

    def test_check_github_release_picks_version_matching_asset(self):
        payload = {
            "tag_name": "v1.2.0",
            "name": "Release 1.2.0",
            "body": "Release body",
            "assets": [
                {"name": "other.zip", "browser_download_url": "http://x/other.zip"},
                {"name": "ZaloPCSyncDrive-v1.2.0.zip", "browser_download_url": "http://x/app.zip"},
            ],
        }
        with patch.object(updater, "_http_get_json", return_value=payload):
            info = updater.check_github_release("owner/repo", "1.1.5")
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(info["download_url"], "http://x/app.zip")
        self.assertEqual(info["notes"], "Release body")

    def test_check_github_release_falls_back_to_first_zip(self):
        payload = {
            "tag_name": "1.2.0",
            "assets": [{"name": "app.zip", "browser_download_url": "http://x/app.zip"}],
        }
        with patch.object(updater, "_http_get_json", return_value=payload):
            info = updater.check_github_release("owner/repo", "1.1.5")
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(info["download_url"], "http://x/app.zip")

    def test_check_github_release_returns_none_without_zip(self):
        payload = {"tag_name": "v1.2.0", "assets": [{"name": "app.rar"}]}
        with patch.object(updater, "_http_get_json", return_value=payload):
            self.assertIsNone(updater.check_github_release("owner/repo", "1.1.5"))


class TestDownload(unittest.TestCase):

    def test_download_update_success(self):
        tmpdir = tempfile.mkdtemp()
        dest = os.path.join(tmpdir, "app.zip")
        try:
            class FakeResp:
                def __init__(self):
                    self._data = b"zipdata"

                def read(self, n=-1):
                    chunk = self._data
                    self._data = b""
                    return chunk

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            with patch("urllib.request.urlopen", return_value=FakeResp()):
                self.assertTrue(updater.download_update("http://x/app.zip", dest))
            self.assertEqual(open(dest, "rb").read(), b"zipdata")
        finally:
            os.remove(dest)
            os.rmdir(tmpdir)

    def test_download_update_failure(self):
        tmpdir = tempfile.mkdtemp()
        dest = os.path.join(tmpdir, "app.zip")
        try:
            with patch("urllib.request.urlopen", side_effect=Exception("network")):
                self.assertFalse(updater.download_update("http://x/app.zip", dest))
        finally:
            os.rmdir(tmpdir)


class TestStageAndScript(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.staging = os.path.join(self.tmpdir, "staging")
        self.zip_path = os.path.join(self.tmpdir, "update.zip")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_zip(self, with_node=True):
        import zipfile
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            zf.writestr("ZaloPCSyncDrive.exe", b"exe")
            if with_node:
                zf.writestr("node_bridge/zalo_bridge.js", b"js")
        return self.zip_path

    def test_stage_update_extracts_zip(self):
        self._make_zip()
        self.assertTrue(updater.stage_update(self.zip_path, self.staging))
        self.assertTrue(os.path.exists(os.path.join(self.staging, "ZaloPCSyncDrive.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.staging, "node_bridge", "zalo_bridge.js")))

    def test_stage_update_failure_on_bad_zip(self):
        with open(self.zip_path, "wb") as f:
            f.write(b"not a zip")
        self.assertFalse(updater.stage_update(self.zip_path, self.staging))

    def test_find_executable(self):
        self._make_zip()
        updater.stage_update(self.zip_path, self.staging)
        found = updater.find_executable(self.staging)
        self.assertTrue(found)
        self.assertTrue(found.lower().endswith("zalopcsyncdrive.exe"))

    def test_find_executable_none_when_missing(self):
        self.assertIsNone(updater.find_executable(self.staging))

    def test_create_update_script_has_copy_and_cleanup(self):
        self._make_zip()
        updater.stage_update(self.zip_path, self.staging)
        script = os.path.join(self.tmpdir, "update.cmd")
        app_dir = os.path.join(self.tmpdir, "app")
        self.assertTrue(updater.create_update_script(self.staging, app_dir, script))
        content = open(script, "r", encoding="utf-8").read()
        self.assertIn("copy /y", content)
        self.assertIn("ZaloPCSyncDrive.exe", content)
        self.assertIn("robocopy", content)
        self.assertIn("rmdir /s /q", content)
        self.assertIn("start", content)

    def test_create_update_script_missing_exe(self):
        script = os.path.join(self.tmpdir, "update.cmd")
        self.assertFalse(updater.create_update_script(self.staging, self.tmpdir, script))


class TestApplyUpdate(unittest.TestCase):

    def test_apply_update_success(self):
        tmpdir = tempfile.mkdtemp()
        try:
            import zipfile
            zip_path = os.path.join(tmpdir, "update.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("ZaloPCSyncDrive.exe", b"exe")
            app_dir = os.path.join(tmpdir, "app")
            os.makedirs(app_dir)

            with patch("subprocess.Popen") as mock_popen:
                result = updater.apply_update(zip_path, app_dir)
            self.assertTrue(result)
            mock_popen.assert_called_once()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_apply_update_fails_on_bad_zip(self):
        tmpdir = tempfile.mkdtemp()
        try:
            zip_path = os.path.join(tmpdir, "update.zip")
            with open(zip_path, "wb") as f:
                f.write(b"garbage")
            with patch("subprocess.Popen") as mock_popen:
                self.assertFalse(updater.apply_update(zip_path, tmpdir))
            mock_popen.assert_not_called()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
