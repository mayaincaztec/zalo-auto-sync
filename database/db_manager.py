"""
SQLite Database Manager
Handles database schema initialization, download history, hash checks, and stats.
"""

import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import DownloadItem, SyncStatus


class DatabaseManager:
    """Thread-safe SQLite database manager for tracking file sync history."""

    def __init__(self, db_path: str = "database.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a shared SQLite connection with row factory configured.

        The connection is created once and reused for the lifetime of the
        manager. All public operations serialize on self._lock, so a single
        connection is safe and avoids the heavy per-operation connect/close
        cost on Windows.
        """
        if self._conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # synchronous=NORMAL avoids a disk flush on every commit (WAL is on).
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        """Closes the shared connection, if open."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    def init_db(self) -> None:
        """Initializes database schema if not exists and ensures missing columns are added."""
        with self._lock:
            conn = self.get_connection()
            # WAL mode is persistent per database file; enables concurrent
            # readers/writers which reduces lock contention between workers.
            conn.execute("PRAGMA journal_mode=WAL;")
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    filepath TEXT,
                    filesize INTEGER,
                    group_name TEXT,
                    message_id TEXT,
                    file_id TEXT,
                    download_status TEXT,
                    drive_status TEXT,
                    created_time TEXT,
                    uploaded_time TEXT,
                    last_scan TEXT,
                    status TEXT,
                    hash TEXT,
                    drive_file_id TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    resumable_uri TEXT,
                    resumable_progress INTEGER DEFAULT 0
                )
            """)
            cursor.execute("PRAGMA table_info(download_history);")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            columns_to_add = [
                ("filename", "TEXT"),
                ("filepath", "TEXT"),
                ("filesize", "INTEGER"),
                ("group_name", "TEXT"),
                ("message_id", "TEXT"),
                ("file_id", "TEXT"),
                ("download_status", "TEXT"),
                ("drive_status", "TEXT"),
                ("created_time", "TEXT"),
                ("uploaded_time", "TEXT"),
                ("last_scan", "TEXT"),
                ("status", "TEXT"),
                ("hash", "TEXT"),
                ("drive_file_id", "TEXT"),
                ("error_message", "TEXT"),
                ("retry_count", "INTEGER DEFAULT 0"),
                ("resumable_uri", "TEXT"),
                ("resumable_progress", "INTEGER DEFAULT 0"),
            ]
            for col_name, col_def in columns_to_add:
                if col_name not in existing_cols:
                    cursor.execute(f"ALTER TABLE download_history ADD COLUMN {col_name} {col_def};")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hash ON download_history(hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_id ON download_history(file_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_group ON download_history(group_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON download_history(status);")
            conn.commit()
        self.init_member_tracking()

    def init_member_tracking(self) -> None:
        """Creates the tables used to store group member info and activity snapshots."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    member_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    is_creator INTEGER DEFAULT 0,
                    last_active_ts INTEGER DEFAULT 0,
                    msg_count INTEGER DEFAULT 0,
                    source_scan INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_member_group
                ON group_members(group_id, member_id)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS member_kick_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT,
                    member_id TEXT,
                    member_name TEXT,
                    kicked_time INTEGER,
                    reason TEXT,
                    status TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kick_group ON member_kick_log(group_id);")
            conn.commit()

    def upsert_members(self, group_id: str, members: List[Dict[str, Any]],
                       clear_missing: bool = True) -> int:
        """Stores a snapshot of members alongside their last-active info.

        Each member row is upserted on (group_id, member_id). When
        clear_missing is True, members no longer present in the snapshot are
        removed so the table mirrors the group's current roster.
        Returns the number of rows upserted.
        """
        if not group_id or not members:
            return 0
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            now = int(datetime.now().timestamp())
            seen: List[str] = []
            for m in members:
                mid = str(m.get("id") or "")
                if not mid:
                    continue
                seen.append(mid)
                cursor.execute("""
                    INSERT INTO group_members
                        (group_id, member_id, member_name, is_admin, is_creator, last_active_ts, msg_count, source_scan)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(group_id, member_id) DO UPDATE SET
                        member_name = excluded.member_name,
                        is_admin = excluded.is_admin,
                        is_creator = excluded.is_creator,
                        last_active_ts = excluded.last_active_ts,
                        msg_count = excluded.msg_count,
                        source_scan = excluded.source_scan
                """, (
                    group_id,
                    mid,
                    str(m.get("name") or ""),
                    1 if m.get("isAdmin") else 0,
                    1 if m.get("isCreator") else 0,
                    int(m.get("lastActive") or 0),
                    int(m.get("msgCount") or 0),
                    now,
                ))
            if clear_missing:
                if seen:
                    placeholders = ",".join("?" * len(seen))
                    cursor.execute(
                        f"DELETE FROM group_members WHERE group_id = ? AND member_id NOT IN ({placeholders})",
                        [group_id] + seen
                    )
                else:
                    cursor.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))
            conn.commit()
            return len(seen)

    def get_members(self, group_id: str) -> List[Dict[str, Any]]:
        """Returns all stored members of a group, sorted by last activity."""
        with self._lock:
            conn = self.get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT member_id, member_name, is_admin, is_creator, last_active_ts, msg_count
                FROM group_members
                WHERE group_id = ?
                ORDER BY last_active_ts DESC
            """, (group_id,))
            return [dict(r) for r in cursor.fetchall()]

    def get_member_activity_overview(self, group_id: str, cutoff_ts: int) -> List[Dict[str, Any]]:
        """Summarizes stored members: who has not been active since cutoff_ts."""
        members = self.get_members(group_id)
        return [
            {
                "id": m["member_id"],
                "name": m["member_name"],
                "isAdmin": bool(m["is_admin"]),
                "isCreator": bool(m["is_creator"]),
                "lastActive": m["last_active_ts"],
                "msgCount": m["msg_count"],
                "inactive": m["last_active_ts"] < cutoff_ts,
            }
            for m in members
        ]

    def log_kick(self, group_id: str, member_id: str, member_name: str,
                 reason: str = "", status: str = "") -> None:
        """Records a kick attempt/result into member_kick_log."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO member_kick_log (group_id, member_id, member_name, kicked_time, reason, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (group_id, member_id, member_name, int(datetime.now().timestamp()), reason, status))
            conn.commit()

    def add_item(self, item: DownloadItem) -> int:
        """Adds a new file item to download history."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO download_history 
                (filename, filepath, filesize, group_name, message_id, file_id, download_status, drive_status, created_time, uploaded_time, last_scan, status, hash, drive_file_id, error_message, retry_count, resumable_uri, resumable_progress)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.filename,
                item.filepath,
                item.filesize,
                item.group_name,
                item.message_id,
                item.file_id,
                item.download_status,
                item.drive_status,
                item.created_time or now_str,
                item.uploaded_time,
                item.last_scan or now_str,
                item.status.value if isinstance(item.status, SyncStatus) else str(item.status),
                item.hash,
                item.drive_file_id,
                item.error_message,
                item.retry_count,
                item.resumable_uri or "",
                item.resumable_progress or 0
            ))
            conn.commit()
            return cursor.lastrowid or 0

    def is_file_processed(self, file_id: str, group_name: str = "") -> bool:
        """Checks if a group file has already been recorded in download history.

        Any row (pending/queued/uploading/completed/skipped) counts as "known" so
        repeated scans don't re-add duplicates. Only 'failed' rows are allowed to
        be retried by a later scan.
        """
        if not file_id:
            return False
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            if group_name:
                cursor.execute(
                    "SELECT id FROM download_history WHERE file_id = ? AND group_name = ? AND status != ?",
                    (file_id, group_name, SyncStatus.FAILED.value)
                )
            else:
                cursor.execute(
                    "SELECT id FROM download_history WHERE file_id = ? AND status != ?",
                    (file_id, SyncStatus.FAILED.value)
                )
            return cursor.fetchone() is not None

    def get_processed_file_ids(self, group_name: str = "") -> set:
        """Returns all known (non-failed) file_ids for a group in one query.

        Used for batch dedup checks during a scan instead of one query per file.
        """
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            if group_name:
                cursor.execute(
                    "SELECT file_id FROM download_history WHERE group_name = ? AND status != ?",
                    (group_name, SyncStatus.FAILED.value)
                )
            else:
                cursor.execute(
                    "SELECT file_id FROM download_history WHERE status != ?",
                    (SyncStatus.FAILED.value,)
                )
            return {row[0] for row in cursor.fetchall()}

    def filter_unprocessed(self, group_name: str, file_ids: list) -> list:
        """Returns only the file_ids that are NOT yet recorded (non-failed).

        Queries the DB once with an IN clause, so scans stay cheap even when the
        download_history table has grown very large.
        """
        file_ids = list(dict.fromkeys(fid for fid in file_ids if fid))
        if not file_ids:
            return []
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(file_ids))
            params = list(file_ids)
            if group_name:
                cursor.execute(
                    f"SELECT file_id FROM download_history WHERE group_name = ? AND status != ? AND file_id IN ({placeholders})",
                    [group_name, SyncStatus.FAILED.value] + params
                )
            else:
                cursor.execute(
                    f"SELECT file_id FROM download_history WHERE status != ? AND file_id IN ({placeholders})",
                    [SyncStatus.FAILED.value] + params
                )
            processed = {row[0] for row in cursor.fetchall()}
            return [fid for fid in file_ids if fid not in processed]

    def update_status(
        self,
        item_id: int,
        status: SyncStatus,
        drive_file_id: Optional[str] = None,
        error_message: Optional[str] = None,
        uploaded_time: Optional[str] = None
    ) -> bool:
        """Updates status and completion details for a file item."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            drive_status = "completed" if status == SyncStatus.COMPLETED else ("failed" if status == SyncStatus.FAILED else ("skipped" if status == SyncStatus.SKIPPED else "uploading"))
            if status == SyncStatus.COMPLETED and not uploaded_time:
                uploaded_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("""
                UPDATE download_history
                SET status = ?, drive_status = ?, drive_file_id = COALESCE(?, drive_file_id),
                    error_message = ?, uploaded_time = COALESCE(?, uploaded_time)
                WHERE id = ?
            """, (
                status.value if isinstance(status, SyncStatus) else str(status),
                drive_status,
                drive_file_id,
                error_message,
                uploaded_time,
                item_id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def increment_retry(self, item_id: int) -> int:
        """Increments retry count for a given item."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE download_history SET retry_count = retry_count + 1 WHERE id = ?", (item_id,))
            conn.commit()
            cursor.execute("SELECT retry_count FROM download_history WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            return row["retry_count"] if row else 0

    def set_resumable_state(self, item_id: int, resumable_uri: str, resumable_progress: int) -> bool:
        """Persists the Google Drive resumable session so a retry can resume
        from the last uploaded byte instead of starting over from zero."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE download_history SET resumable_uri = ?, resumable_progress = ? WHERE id = ?",
                (resumable_uri or "", int(resumable_progress or 0), item_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_resumable_state(self, item_id: int) -> bool:
        """Clears the resumable session after a successful upload."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE download_history SET resumable_uri = '', resumable_progress = 0 WHERE id = ?",
                (item_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_file_downloaded(self, file_hash: str) -> bool:
        """Checks whether this content hash completed local download before."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM download_history WHERE hash = ? AND status = ?",
                (file_hash, SyncStatus.COMPLETED.value)
            )
            return cursor.fetchone() is not None

    def is_file_uploaded(self, file_hash: str) -> bool:
        """Backward-compatible alias retained for existing database callers."""
        return self.is_file_downloaded(file_hash)

    def _row_to_item(self, row) -> DownloadItem:
        return DownloadItem(
            id=row["id"],
            filename=row["filename"],
            filepath=row["filepath"] or "",
            filesize=row["filesize"] or 0,
            group_name=row["group_name"] if "group_name" in row.keys() else "",
            message_id=row["message_id"] if "message_id" in row.keys() else "",
            file_id=row["file_id"] if "file_id" in row.keys() else "",
            download_status=row["download_status"] if "download_status" in row.keys() else "pending",
            drive_status=row["drive_status"] if "drive_status" in row.keys() else "pending",
            created_time=row["created_time"],
            uploaded_time=row["uploaded_time"],
            last_scan=row["last_scan"] if "last_scan" in row.keys() else "",
            status=SyncStatus(row["status"]) if row["status"] in [s.value for s in SyncStatus] else SyncStatus.PENDING,
            hash=row["hash"] or "",
            drive_file_id=row["drive_file_id"],
            error_message=row["error_message"],
            retry_count=row["retry_count"] or 0,
            resumable_uri=row["resumable_uri"] if "resumable_uri" in row.keys() else "",
            resumable_progress=row["resumable_progress"] if "resumable_progress" in row.keys() else 0
        )

    def get_item_by_hash(self, file_hash: str) -> Optional[DownloadItem]:
        """Retrieves item by hash."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM download_history WHERE hash = ? ORDER BY id DESC LIMIT 1", (file_hash,))
            row = cursor.fetchone()
            return self._row_to_item(row) if row else None

    def get_resumable_state(self, file_id: str, group_name: str = "") -> Tuple[str, int]:
        """Returns (resumable_uri, resumable_progress) from the most recent
        failed row for the same file, so a re-scan can resume a Drive upload."""
        if not file_id:
            return ("", 0)
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            if group_name:
                cursor.execute(
                    "SELECT resumable_uri, resumable_progress FROM download_history "
                    "WHERE file_id = ? AND group_name = ? AND resumable_uri != '' "
                    "ORDER BY id DESC LIMIT 1",
                    (file_id, group_name)
                )
            else:
                cursor.execute(
                    "SELECT resumable_uri, resumable_progress FROM download_history "
                    "WHERE file_id = ? AND resumable_uri != '' "
                    "ORDER BY id DESC LIMIT 1",
                    (file_id,)
                )
            row = cursor.fetchone()
            if row and row["resumable_uri"]:
                return (row["resumable_uri"], row["resumable_progress"] or 0)
            return ("", 0)

    def get_all_items(self, limit: int = 100) -> List[DownloadItem]:
        """Returns history items sorted by latest first."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM download_history ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_item(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Aggregates local download statistics in a single query."""
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END), 0) AS uploaded,
                    COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END), 0) AS failed,
                    COALESCE(SUM(CASE WHEN status = ? THEN 1 ELSE 0 END), 0) AS pending,
                    COALESCE(SUM(CASE WHEN status = ? THEN filesize ELSE 0 END), 0) AS total_bytes
                FROM download_history
            """, (
                SyncStatus.COMPLETED.value,
                SyncStatus.FAILED.value,
                SyncStatus.PENDING.value,
                SyncStatus.COMPLETED.value,
            ))
            row = cursor.fetchone()

            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute(
                "SELECT COUNT(*) FROM download_history WHERE uploaded_time LIKE ? AND status = ?",
                (f"{today}%", SyncStatus.COMPLETED.value)
            )
            today_count = cursor.fetchone()[0]

            return {
                "total_files": row["total"] or 0,
                "downloaded_files": row["uploaded"],
                "uploaded_files": row["uploaded"],  # compatibility alias
                "error_files": row["failed"],
                "pending_files": row["pending"],
                "total_bytes": row["total_bytes"],
                "today_count": today_count
            }
