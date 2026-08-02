"""
Google Drive Service
Handles Google Drive API OAuth2 authorization, folder creation/lookup, and resumable file uploads.
"""

import os
import time
from typing import Any, Callable, Dict, Optional

try:
    import httplib2
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_SDK_AVAILABLE = True
except ImportError:
    GDRIVE_SDK_AVAILABLE = False


SCOPES = ['https://www.googleapis.com/auth/drive.file']
HTTP_TIMEOUT = 60  # seconds; prevents uploads hanging forever on dead connections


class GoogleDriveService:
    """Service wrapper for official Google Drive API v3 operations."""

    def __init__(self, credentials_file: str = "credentials.json", token_file: str = "token.json"):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.creds = None

    def is_sdk_available(self) -> bool:
        return GDRIVE_SDK_AVAILABLE

    def authenticate(self) -> bool:
        """Authenticates with Google Drive using OAuth2 credentials."""
        if not GDRIVE_SDK_AVAILABLE:
            raise RuntimeError("Google Client Library not installed. Run `pip install google-api-python-client google-auth-oauthlib`.")

        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                # Search for valid credentials file across common candidate paths
                candidate_paths = [
                    self.credentials_file,
                    "credentials.json",
                    "client_secret.json",
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json"),
                    os.path.join(os.path.dirname(os.path.dirname(__file__)), "client_secret.json"),
                    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "credentials.json"),
                ]
                found_cred_path = None
                for path in candidate_paths:
                    if path and os.path.exists(path):
                        found_cred_path = path
                        break

                if not found_cred_path:
                    raise FileNotFoundError(
                        f"OAuth credentials file '{self.credentials_file}' or 'client_secret.json' not found in working directory. "
                        "Please download Desktop OAuth Client Credentials from Google Cloud Console and save as 'credentials.json'."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(found_cred_path, SCOPES)
                self.creds = flow.run_local_server(port=0)

            # Save the credentials for next run
            with open(self.token_file, 'w', encoding='utf-8') as token:
                token.write(self.creds.to_json())

        self.service = build(
            'drive', 'v3',
            http=AuthorizedHttp(self.creds, http=httplib2.Http(timeout=HTTP_TIMEOUT)),
            cache_discovery=False
        )
        return True

    def get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """Finds existing folder or creates a new folder in Google Drive."""
        if not self.service:
            self.authenticate()

        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])

        if items:
            return items[0]['id']

        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            folder_metadata['parents'] = [parent_id]

        folder = self.service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')

    def check_file_exists(self, filename: str, folder_id: str) -> Optional[str]:
        """Checks if a file with exact name exists in the specified target folder."""
        if not self.service:
            self.authenticate()

        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        return items[0]['id'] if items else None

    def upload_file(
        self,
        filepath: str,
        folder_id: str,
        duplicate_action: str = "rename",  # "skip", "rename", "overwrite"
        progress_callback: Optional[Callable[[int, int], None]] = None,
        resumable_uri: Optional[str] = None,
        resumable_progress: int = 0,
        resume_callback: Optional[Callable[[str, int], None]] = None
    ) -> Dict[str, Any]:
        """Uploads a local file to Google Drive with progress callbacks.

        Args:
            filepath: Path to local file.
            folder_id: Destination Google Drive folder ID.
            duplicate_action: How to handle existing file ("skip", "rename", "overwrite").
            progress_callback: Optional function receiving (bytes_uploaded, total_bytes).
            resumable_uri: Resumable session URI from a previous interrupted
                attempt; when provided the upload resumes instead of restarting.
            resumable_progress: Bytes already uploaded in the previous session.
            resume_callback: Optional function called after each chunk with
                (resumable_uri, bytes_uploaded) so callers can persist the
                session and resume later.

        Returns:
            Dict containing drive file id, name, and status.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Local file not found: {filepath}")

        filename = os.path.basename(filepath)
        total_size = os.path.getsize(filepath)

        if not self.service:
            self.authenticate()

        existing_file_id = None
        if not resumable_uri:
            existing_file_id = self.check_file_exists(filename, folder_id)

        if existing_file_id:
            if duplicate_action == "skip":
                return {
                    "id": existing_file_id,
                    "name": filename,
                    "status": "skipped",
                    "message": "File already exists in Drive folder. Skipped upload."
                }
            elif duplicate_action == "rename":
                base, ext = os.path.splitext(filename)
                timestamp = int(time.time())
                filename = f"{base}_{timestamp}{ext}"
            elif duplicate_action == "overwrite":
                # Delete existing file before uploading fresh copy
                try:
                    self.service.files().delete(fileId=existing_file_id).execute()
                except Exception:
                    pass

        file_metadata = {
            'name': filename,
            'parents': [folder_id] if folder_id else []
        }

        media = MediaFileUpload(filepath, resumable=True)
        request = self.service.files().create(body=file_metadata, media_body=media, fields='id, name, webViewLink')

        # Restore a previously interrupted resumable session: point the request
        # at the saved session URI and let next_chunk() query the server for the
        # actual uploaded bytes before continuing.
        if resumable_uri:
            request.resumable_uri = resumable_uri
            request.resumable_progress = int(resumable_progress or 0)
            request._in_error_state = True

        def _persist_resume_state():
            if resume_callback and request.resumable_uri:
                resume_callback(request.resumable_uri, request.resumable_progress)

        response = None
        try:
            while response is None:
                status, response = request.next_chunk()
                if status and progress_callback:
                    progress_callback(int(status.resumable_progress), total_size)
                _persist_resume_state()
        except Exception:
            _persist_resume_state()
            raise

        if progress_callback:
            progress_callback(total_size, total_size)

        return {
            "id": response.get('id'),
            "name": response.get('name'),
            "status": "completed",
            "webViewLink": response.get('webViewLink')
        }
