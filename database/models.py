"""
Database Models & Enums
Defines data structures for sync items and status tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SyncStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class DownloadItem:
    """Represents a file item tracked in local download history.

    Drive-related fields remain for backward compatibility with existing
    SQLite databases created by releases before local-only mode.
    """

    id: Optional[int] = None
    filename: str = ""
    filepath: str = ""
    filesize: int = 0
    group_name: str = ""
    message_id: str = ""
    file_id: str = ""
    download_status: str = "pending"  # "pending", "downloading", "downloaded", "failed"
    drive_status: str = "not_required"  # Legacy column; no cloud upload in local-only mode
    created_time: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    uploaded_time: Optional[str] = None
    last_scan: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    status: SyncStatus = SyncStatus.PENDING
    hash: str = ""
    drive_file_id: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    resumable_uri: str = ""
    resumable_progress: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "filepath": self.filepath,
            "filesize": self.filesize,
            "group_name": self.group_name,
            "message_id": self.message_id,
            "file_id": self.file_id,
            "download_status": self.download_status,
            "drive_status": self.drive_status,
            "created_time": self.created_time,
            "uploaded_time": self.uploaded_time,
            "last_scan": self.last_scan,
            "status": self.status.value if isinstance(self.status, SyncStatus) else str(self.status),
            "hash": self.hash,
            "drive_file_id": self.drive_file_id,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "resumable_uri": self.resumable_uri,
            "resumable_progress": self.resumable_progress
        }
