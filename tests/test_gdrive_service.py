"""
Unit Tests for GoogleDriveService
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from zalo_drive_sync.services.gdrive_service import GoogleDriveService, SCOPES


class TestGoogleDriveService(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.creds_file = os.path.join(self.dir, "credentials.json")
        with open(self.creds_file, "w", encoding="utf-8") as f:
            f.write("{}")
        self.token_file = os.path.join(self.dir, "token.json")
        self.service = GoogleDriveService(
            credentials_file=self.creds_file,
            token_file=self.token_file,
        )

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # --- SDK availability ---

    def test_is_sdk_available_true(self):
        self.assertTrue(self.service.is_sdk_available())

    def test_is_sdk_available_false_when_missing(self):
        with patch("zalo_drive_sync.services.gdrive_service.GDRIVE_SDK_AVAILABLE", False):
            self.assertFalse(self.service.is_sdk_available())

    def test_sdk_fallback_when_imports_missing(self):
        # Verified in a fresh interpreter: if google libs are unavailable the
        # module must still import with GDRIVE_SDK_AVAILABLE = False.
        code = (
            "import sys\n"
            "sys.modules['httplib2'] = None\n"
            "sys.modules['google'] = None\n"
            "sys.modules['google.auth'] = None\n"
            "sys.modules['google.oauth2'] = None\n"
            "sys.modules['google.auth.transport'] = None\n"
            "sys.modules['google_auth_httplib2'] = None\n"
            "sys.modules['google_auth_oauthlib'] = None\n"
            "sys.modules['googleapiclient'] = None\n"
            "import zalo_drive_sync.services.gdrive_service as m\n"
            "assert m.GDRIVE_SDK_AVAILABLE is False\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": os.pathsep.join([os.path.dirname(os.path.dirname(os.path.dirname(__file__))), os.environ.get("PYTHONPATH", "")])}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    # --- authenticate ---

    def test_authenticate_raises_without_sdk(self):
        with patch("zalo_drive_sync.services.gdrive_service.GDRIVE_SDK_AVAILABLE", False):
            with self.assertRaises(RuntimeError):
                self.service.authenticate()

    def test_authenticate_valid_token_skips_flow(self):
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write("{}")
        creds = MagicMock()
        creds.valid = True
        with patch("zalo_drive_sync.services.gdrive_service.Credentials.from_authorized_user_file", return_value=creds) as from_file, \
             patch("zalo_drive_sync.services.gdrive_service.build") as build:
            self.assertTrue(self.service.authenticate())
        from_file.assert_called_once_with(self.token_file, SCOPES)
        self.assertTrue(build.called)
        kwargs = build.call_args.kwargs
        self.assertIn("http", kwargs)
        self.assertFalse(kwargs["cache_discovery"])
        self.assertIs(self.service.creds, creds)
        self.assertIsNotNone(self.service.service)

    def test_authenticate_refreshes_expired_token(self):
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write("{}")
        creds = MagicMock()
        creds.valid = False
        creds.expired = True
        creds.refresh_token = "rt"
        creds.to_json.return_value = '{"token": "refreshed"}'
        with patch("zalo_drive_sync.services.gdrive_service.Credentials.from_authorized_user_file", return_value=creds), \
             patch("zalo_drive_sync.services.gdrive_service.Request") as req_cls, \
             patch("zalo_drive_sync.services.gdrive_service.build"):
            self.assertTrue(self.service.authenticate())
        creds.refresh.assert_called_once_with(req_cls.return_value)

    def test_authenticate_runs_flow_when_no_token(self):
        creds = MagicMock()
        creds.valid = True
        creds.to_json.return_value = '{"token": "fresh"}'
        with patch("zalo_drive_sync.services.gdrive_service.InstalledAppFlow") as flow_cls, \
             patch("zalo_drive_sync.services.gdrive_service.build"):
            flow_cls.from_client_secrets_file.return_value.run_local_server.return_value = creds
            self.assertTrue(self.service.authenticate())
        flow_cls.from_client_secrets_file.assert_called_once_with(self.creds_file, SCOPES)
        flow_cls.from_client_secrets_file.return_value.run_local_server.assert_called_once_with(port=0)
        # token file written
        self.assertTrue(os.path.exists(self.token_file))

    def test_authenticate_raises_when_no_credentials_found(self):
        with patch("zalo_drive_sync.services.gdrive_service.os.path.exists", return_value=False):
            with self.assertRaises(FileNotFoundError):
                self.service.authenticate()

    # --- get_or_create_folder ---

    def test_get_or_create_folder_returns_existing(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "fld1", "name": "ZaloSync"}]}
        self.service.service = svc
        self.assertEqual(self.service.get_or_create_folder("ZaloSync"), "fld1")
        svc.files().create.assert_not_called()

    def test_get_or_create_folder_creates(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        svc.files().create().execute.return_value = {"id": "newfld"}
        self.service.service = svc
        self.assertEqual(self.service.get_or_create_folder("ZaloSync"), "newfld")
        body = svc.files().create.call_args.kwargs["body"]
        self.assertEqual(body["name"], "ZaloSync")
        self.assertEqual(body["mimeType"], "application/vnd.google-apps.folder")

    def test_get_or_create_folder_with_parent_query(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "fld1"}]}
        self.service.service = svc
        self.service.get_or_create_folder("ZaloSync", parent_id="parent_1")
        q = svc.files().list.call_args.kwargs["q"]
        self.assertIn("'parent_1' in parents", q)

    def test_get_or_create_folder_authenticates_when_needed(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "fld1"}]}
        self.service.service = None
        with patch.object(self.service, "authenticate", return_value=True) as auth:
            self.service.service = svc  # set before call; authenticate not needed
        # verify authenticate is invoked when service is None
        self.service.service = None
        with patch.object(self.service, "authenticate", return_value=True) as auth:
            self.service.service = svc
            self.assertEqual(self.service.get_or_create_folder("Z"), "fld1")
            self.assertFalse(auth.called)  # service already set

    def test_get_or_create_folder_authenticates_when_service_none(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "fld1"}]}
        self.service.service = None
        with patch.object(self.service, "authenticate") as auth:
            auth.side_effect = lambda: setattr(self.service, "service", svc)
            self.assertEqual(self.service.get_or_create_folder("Z"), "fld1")
        auth.assert_called_once()

    def test_get_or_create_folder_creates_with_parent_metadata(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        svc.files().create().execute.return_value = {"id": "newfld"}
        self.service.service = svc
        self.assertEqual(self.service.get_or_create_folder("ZaloSync", parent_id="parent_1"), "newfld")
        body = svc.files().create.call_args.kwargs["body"]
        self.assertEqual(body["parents"], ["parent_1"])

    # --- check_file_exists ---

    def test_check_file_exists_found(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "file_1", "name": "a.pdf"}]}
        self.service.service = svc
        self.assertEqual(self.service.check_file_exists("a.pdf", "folder_1"), "file_1")

    def test_check_file_exists_none(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        self.service.service = svc
        self.assertIsNone(self.service.check_file_exists("a.pdf", "folder_1"))

    def test_check_file_exists_builds_query(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        self.service.service = svc
        self.service.check_file_exists("a.pdf", "folder_1")
        q = svc.files().list.call_args.kwargs["q"]
        self.assertIn("name = 'a.pdf'", q)
        self.assertIn("'folder_1' in parents", q)

    def test_check_file_exists_authenticates_when_service_none(self):
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "file_1"}]}
        self.service.service = None
        with patch.object(self.service, "authenticate") as auth:
            auth.side_effect = lambda: setattr(self.service, "service", svc)
            self.assertEqual(self.service.check_file_exists("a.pdf", "folder_1"), "file_1")
        auth.assert_called_once()

    # --- upload_file ---

    def _make_local_file(self, name="doc.pdf", content=b"data"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_upload_file_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.service.upload_file(os.path.join(self.dir, "ghost.pdf"), "folder_1")

    def test_upload_file_skip_duplicate(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "existing_id"}]}
        self.service.service = svc
        result = self.service.upload_file(local, "folder_1", duplicate_action="skip")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["id"], "existing_id")
        svc.files().create.assert_not_called()

    def _mock_upload(self, svc, next_chunks):
        """Configures create() to yield the given (status, response) pairs."""
        create = svc.files().create.return_value
        create.next_chunk.side_effect = next_chunks
        return create

    def test_upload_file_rename_duplicate(self):
        local = self._make_local_file("doc.pdf")
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "existing_id"}]}
        self._mock_upload(svc, [(None, {"id": "new_id", "name": "doc_1000.pdf", "webViewLink": "url"})])
        self.service.service = svc
        with patch("zalo_drive_sync.services.gdrive_service.time.time", return_value=1000.0):
            result = self.service.upload_file(local, "folder_1", duplicate_action="rename")
        self.assertEqual(result["status"], "completed")
        body = svc.files().create.call_args.kwargs["body"]
        self.assertEqual(body["name"], "doc_1000.pdf")

    def test_upload_file_overwrite_duplicate_deletes_existing(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "existing_id"}]}
        self._mock_upload(svc, [(None, {"id": "new_id", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        result = self.service.upload_file(local, "folder_1", duplicate_action="overwrite")
        svc.files().delete.assert_called_once_with(fileId="existing_id")
        self.assertEqual(result["status"], "completed")

    def test_upload_file_overwrite_delete_error_swallowed(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "existing_id"}]}
        svc.files().delete.side_effect = Exception("gone")
        self._mock_upload(svc, [(None, {"id": "new_id", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        result = self.service.upload_file(local, "folder_1", duplicate_action="overwrite")
        self.assertEqual(result["status"], "completed")

    def test_upload_file_unknown_duplicate_action_uploads_original_name(self):
        # An unrecognized duplicate_action falls through (no rename, no delete)
        local = self._make_local_file("doc.pdf")
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": [{"id": "existing_id"}]}
        self._mock_upload(svc, [(None, {"id": "new_id", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        result = self.service.upload_file(local, "folder_1", duplicate_action="bogus")
        self.assertEqual(result["status"], "completed")
        body = svc.files().create.call_args.kwargs["body"]
        self.assertEqual(body["name"], "doc.pdf")
        svc.files().delete.assert_not_called()

    def test_upload_file_success_with_progress(self):
        local = self._make_local_file(content=b"x" * 100)
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        status = MagicMock()
        status.resumable_progress = 50
        self._mock_upload(svc, [(status, None), (None, {"id": "id1", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        progress = MagicMock()
        result = self.service.upload_file(local, "folder_1", progress_callback=progress)
        self.assertEqual(result["id"], "id1")
        self.assertEqual(result["status"], "completed")
        progress.assert_any_call(50, 100)
        progress.assert_any_call(100, 100)

    def test_upload_file_completes_no_progress_callback(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        self._mock_upload(svc, [(None, {"id": "id1", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        result = self.service.upload_file(local, "folder_1")
        self.assertEqual(result["status"], "completed")

    def test_upload_file_authenticates_when_no_service(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        self._mock_upload(svc, [(None, {"id": "id1", "name": "doc.pdf", "webViewLink": "url"})])
        with patch.object(self.service, "authenticate") as auth:
            auth.side_effect = lambda: setattr(self.service, "service", svc)
            result = self.service.upload_file(local, "folder_1")
        self.assertEqual(result["status"], "completed")
        auth.assert_called_once()

    # --- resumable upload ---

    def test_upload_resumes_with_saved_uri_skips_dup_check(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        self._mock_upload(svc, [(None, {"id": "id1", "name": "doc.pdf", "webViewLink": "url"})])
        self.service.service = svc
        result = self.service.upload_file(
            local, "folder_1",
            resumable_uri="https://session/xyz",
            resumable_progress=42
        )
        self.assertEqual(result["status"], "completed")
        request = svc.files().create.return_value
        self.assertEqual(request.resumable_uri, "https://session/xyz")
        self.assertEqual(request.resumable_progress, 42)
        self.assertTrue(request._in_error_state)

    def test_upload_resume_callback_receives_session(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        create = svc.files().create.return_value
        # First chunk: no response yet but resumable_uri becomes known.
        def first_chunk():
            create.resumable_uri = "https://session/live"
            create.resumable_progress = 100
            return None, None
        create.next_chunk.side_effect = [
            first_chunk(),
            (None, {"id": "id1", "name": "doc.pdf", "webViewLink": "url"})
        ]
        self.service.service = svc
        seen = []
        result = self.service.upload_file(local, "folder_1", resume_callback=lambda uri, prog: seen.append((uri, prog)))
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any(uri == "https://session/live" for uri, _ in seen))
        self.assertTrue(any(prog == 100 for _, prog in seen))

    def test_upload_resume_callback_fires_on_exception(self):
        local = self._make_local_file()
        svc = MagicMock()
        svc.files().list().execute.return_value = {"files": []}
        create = svc.files().create.return_value
        def raise_chunk():
            create.resumable_uri = "https://session/partial"
            create.resumable_progress = 75
            raise ConnectionError("broken pipe")
        create.next_chunk.side_effect = raise_chunk
        self.service.service = svc
        seen = []
        with self.assertRaises(ConnectionError):
            self.service.upload_file(local, "folder_1", resume_callback=lambda uri, prog: seen.append((uri, prog)))
        self.assertEqual(seen, [("https://session/partial", 75)])


if __name__ == "__main__":
    unittest.main()
