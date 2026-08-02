"""
Upload Queue Worker Module
Thread-safe upload queue managing parallel worker threads, retries, timeouts, and progress callbacks.
"""

import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.gdrive_service import GoogleDriveService


class UploadTask:
    def __init__(self, item: DownloadItem, gdrive_folder_id: str, duplicate_action: str = "rename"):
        self.item = item
        self.gdrive_folder_id = gdrive_folder_id
        self.duplicate_action = duplicate_action


class UploadQueueManager:
    """Manages thread pool worker queue for file uploads."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        gdrive_service: GoogleDriveService,
        max_workers: int = 2,
        max_retries: int = 3,
        status_callback: Optional[Callable[[DownloadItem, str, int], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None
    ):
        self.db_manager = db_manager
        self.gdrive_service = gdrive_service
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.status_callback = status_callback  # (item, message, progress_percent)
        self.log_callback = log_callback

        self.task_queue: queue.Queue = queue.Queue()
        self.executor: Optional[ThreadPoolExecutor] = None
        self.is_running = False
        self._lock = threading.Lock()

    def log(self, level: str, message: str):
        if self.log_callback:
            self.log_callback(level, message)

    def start(self):
        """Starts upload queue workers."""
        with self._lock:
            if self.is_running:
                return
            self.is_running = True
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="UploadWorker")
            for _ in range(self.max_workers):
                self.executor.submit(self._worker_loop)
            self.log("INFO", f"Upload queue manager started with {self.max_workers} worker threads.")

    def stop(self):
        """Stops queue workers cleanly."""
        with self._lock:
            if not self.is_running:
                return
            self.is_running = False
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None
            self.log("INFO", "Upload queue manager stopped.")

    def add_item(self, item: DownloadItem, gdrive_folder_id: str, duplicate_action: str = "rename"):
        """Adds a download item task to the queue."""
        task = UploadTask(item, gdrive_folder_id, duplicate_action)
        self.db_manager.update_status(item.id, SyncStatus.QUEUED)
        item.status = SyncStatus.QUEUED
        if self.status_callback:
            self.status_callback(item, "In Queue", 0)
        self.task_queue.put(task)

    def _worker_loop(self):
        """Worker loop processing queued upload tasks."""
        while self.is_running:
            try:
                task: UploadTask = self.task_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._process_upload(task)
            except Exception as e:
                self.log("ERROR", f"Unexpected error processing '{task.item.filename}': {e}")
            finally:
                self.task_queue.task_done()

    def _process_upload(self, task: UploadTask):
        item = task.item
        self.log("INFO", f"Starting upload for '{item.filename}' to Google Drive...")

        if not item.filepath or not os.path.isfile(item.filepath):
            err_msg = f"File not found locally: {item.filepath}"
            item.status = SyncStatus.FAILED
            item.error_message = err_msg
            self.db_manager.update_status(item.id, SyncStatus.FAILED, error_message=err_msg)
            self.log("ERROR", f"Skipping '{item.filename}': {err_msg}")
            if self.status_callback:
                self.status_callback(item, "Failed: file not found", 0)
            return

        item.status = SyncStatus.UPLOADING
        self.db_manager.update_status(item.id, SyncStatus.UPLOADING)
        if self.status_callback:
            self.status_callback(item, "Uploading...", 0)

        def progress_handler(bytes_sent: int, total_bytes: int):
            if total_bytes > 0:
                percent = int((bytes_sent / total_bytes) * 100)
                if percent != progress_handler.last_percent:
                    progress_handler.last_percent = percent
                    if self.status_callback:
                        self.status_callback(item, f"Uploading ({percent}%)", percent)

        progress_handler.last_percent = -1

        # Track the Google Drive resumable session so a failed attempt can
        # resume from the last uploaded byte instead of starting from zero.
        resumable_uri = item.resumable_uri or ""
        resumable_progress = item.resumable_progress or 0

        def resume_handler(uri: str, progress: int):
            nonlocal resumable_uri, resumable_progress
            resumable_uri = uri
            resumable_progress = progress
            self.db_manager.set_resumable_state(item.id, uri, progress)

        retry_count = 0
        success = False

        while retry_count <= self.max_retries and self.is_running:
            try:
                result = self.gdrive_service.upload_file(
                    filepath=item.filepath,
                    folder_id=task.gdrive_folder_id,
                    duplicate_action=task.duplicate_action,
                    progress_callback=progress_handler,
                    resumable_uri=resumable_uri or None,
                    resumable_progress=resumable_progress,
                    resume_callback=resume_handler
                )

                if result.get("status") == "skipped":
                    item.status = SyncStatus.SKIPPED
                    self.db_manager.update_status(item.id, SyncStatus.SKIPPED, error_message="Skipped duplicate")
                    self.db_manager.clear_resumable_state(item.id)
                    self.log("INFO", f"Skipped '{item.filename}' (already in Drive).")
                    if self.status_callback:
                        self.status_callback(item, "Skipped", 100)
                else:
                    drive_id = result.get("id")
                    item.status = SyncStatus.COMPLETED
                    item.drive_file_id = drive_id
                    self.db_manager.update_status(item.id, SyncStatus.COMPLETED, drive_file_id=drive_id)
                    self.db_manager.clear_resumable_state(item.id)
                    self.log("INFO", f"Successfully uploaded '{item.filename}' (Drive ID: {drive_id}).")
                    if self.status_callback:
                        self.status_callback(item, "Completed", 100)

                success = True
                break

            except Exception as e:
                retry_count += 1
                self.db_manager.increment_retry(item.id)
                item.retry_count = retry_count

                if retry_count <= self.max_retries:
                    wait_time = 2 ** retry_count  # Exponential backoff
                    resume_note = f" Resuming from {resumable_progress}/{item.filesize} bytes." if resumable_uri else ""
                    self.log("WARNING", f"Upload failed for '{item.filename}': {e}. Retrying in {wait_time}s ({retry_count}/{self.max_retries})...{resume_note}")
                    if self.status_callback:
                        self.status_callback(item, f"Retry {retry_count}/{self.max_retries}...", 0)
                    time.sleep(wait_time)
                else:
                    err_msg = str(e)
                    item.status = SyncStatus.FAILED
                    item.error_message = err_msg
                    self.db_manager.update_status(item.id, SyncStatus.FAILED, error_message=err_msg)
                    self.log("ERROR", f"Failed uploading '{item.filename}' after {self.max_retries} retries: {err_msg}")
                    if self.status_callback:
                        self.status_callback(item, f"Failed: {err_msg[:30]}", 0)
