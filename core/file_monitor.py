"""
File Monitor Module
Monitors Zalo download directory using Watchdog, filters extensions, checks file stability, and notifies queue.
"""

import os
import time
from typing import Callable, List, Optional

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

from zalo_drive_sync.core.hasher import calculate_sha256
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.zalo_service import wait_for_file_stability


class ZaloFileHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Watchdog event handler for monitoring newly downloaded files."""

    def __init__(
        self,
        allowed_extensions: List[str],
        db_manager: DatabaseManager,
        file_callback: Callable[[DownloadItem], None],
        log_callback: Optional[Callable[[str, str], None]] = None
    ):
        self.allowed_extensions = [ext.lower().strip() for ext in allowed_extensions]
        self.db_manager = db_manager
        self.file_callback = file_callback
        self.log_callback = log_callback

    def log(self, level: str, message: str):
        if self.log_callback:
            self.log_callback(level, message)

    def on_created(self, event):
        if hasattr(event, 'is_directory') and event.is_directory:
            return
        self.process_filepath(getattr(event, 'src_path', ''))

    def on_modified(self, event):
        if hasattr(event, 'is_directory') and event.is_directory:
            return
        # Some downloaders create temporary files and modify them on completion
        self.process_filepath(getattr(event, 'src_path', ''))

    def process_filepath(self, filepath: str):
        if not os.path.exists(filepath):
            return

        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()

        # Skip temporary files (.tmp, .crdownload, .part)
        if ext in ['.tmp', '.crdownload', '.part', '.download']:
            return

        if self.allowed_extensions and ext not in self.allowed_extensions:
            self.log("DEBUG", f"File '{filename}' ignored (extension '{ext}' not in allowed list).")
            return

        self.log("INFO", f"New file detected: {filename}. Waiting for download completion...")

        # Wait for file download to complete and release write lock
        if not wait_for_file_stability(filepath, check_interval=1.0, timeout=20.0):
            self.log("WARNING", f"File '{filename}' is still locked or incomplete. Skipping for now.")
            return

        filesize = os.path.getsize(filepath)
        if filesize == 0:
            self.log("WARNING", f"File '{filename}' is empty (0 bytes). Skipping.")
            return

        try:
            file_hash = calculate_sha256(filepath)
        except Exception as e:
            self.log("ERROR", f"Failed to compute SHA-256 hash for '{filename}': {e}")
            return

        # Check duplicate in SQLite database
        if self.db_manager.is_file_uploaded(file_hash):
            self.log("INFO", f"File '{filename}' (hash: {file_hash[:8]}...) has already been uploaded. Skipping duplicate.")
            return

        existing_item = self.db_manager.get_item_by_hash(file_hash)
        if existing_item and existing_item.status == SyncStatus.COMPLETED:
            self.log("INFO", f"File '{filename}' already marked completed in history. Skipping.")
            return

        item = DownloadItem(
            filename=filename,
            filepath=filepath,
            filesize=filesize,
            status=SyncStatus.PENDING,
            hash=file_hash
        )

        item_id = self.db_manager.add_item(item)
        item.id = item_id

        self.log("INFO", f"Queuing file '{filename}' ({filesize / 1024:.1f} KB) for upload.")
        self.file_callback(item)


class FileMonitorManager:
    """Manager for directory observation."""

    def __init__(
        self,
        directory: str,
        extensions: List[str],
        db_manager: DatabaseManager,
        file_callback: Callable[[DownloadItem], None],
        log_callback: Optional[Callable[[str, str], None]] = None
    ):
        self.directory = directory
        self.extensions = extensions
        self.db_manager = db_manager
        self.file_callback = file_callback
        self.log_callback = log_callback
        self.observer = None
        self.is_running = False

    def start(self) -> bool:
        """Starts directory watcher."""
        if not WATCHDOG_AVAILABLE:
            if self.log_callback:
                self.log_callback("ERROR", "Watchdog package not available. Install watchdog with `pip install watchdog`.")
            return False

        if not os.path.exists(self.directory):
            os.makedirs(self.directory, exist_ok=True)

        handler = ZaloFileHandler(
            allowed_extensions=self.extensions,
            db_manager=self.db_manager,
            file_callback=self.file_callback,
            log_callback=self.log_callback
        )

        self.observer = Observer()
        self.observer.schedule(handler, self.directory, recursive=False)
        self.observer.start()
        self.is_running = True
        if self.log_callback:
            self.log_callback("INFO", f"Started monitoring folder: {self.directory}")

        # Perform initial scan of existing files in the directory
        self.scan_existing_files(handler)
        return True

    def scan_existing_files(self, handler: ZaloFileHandler):
        """Scans folder for existing files that haven't been uploaded yet."""
        try:
            for entry in os.scandir(self.directory):
                if entry.is_file():
                    handler.process_filepath(entry.path)
        except Exception as e:
            if self.log_callback:
                self.log_callback("ERROR", f"Error scanning existing files in directory: {e}")

    def stop(self):
        """Stops directory watcher."""
        if self.observer and self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            if self.log_callback:
                self.log_callback("INFO", "Stopped file monitor.")
