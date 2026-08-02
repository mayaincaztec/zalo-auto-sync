"""
Zalo Group Sync Engine
Orchestrates the workflow:
Open Zalo -> Open Group -> Scan Group Files -> Identify New Files via SQLite ->
Download File -> Wait & Verify Download -> Enqueue Upload to Drive -> Update SQLite History.
"""

import os
import time
import threading
import logging
from typing import Callable, List, Optional
from datetime import datetime

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.core.hasher import calculate_sha256
from zalo_drive_sync.core.upload_queue import UploadQueueManager
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.gdrive_service import GoogleDriveService
from zalo_drive_sync.services.zalo_controller import GroupFile, ZaloController

logger = logging.getLogger("ZaloPCSync")


class ZaloGroupSyncEngine:
    """Main execution engine for scanning Zalo Group files and uploading to Drive."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: DatabaseManager,
        gdrive_service: GoogleDriveService,
        log_callback: Optional[Callable[[str, str], None]] = None,
        item_callback: Optional[Callable[[DownloadItem, str, int], None]] = None,
        qrcode_callback: Optional[Callable[[str], None]] = None,
        zalo_controller: Optional[ZaloController] = None
    ):
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.gdrive_service = gdrive_service
        self.log_callback = log_callback
        self.item_callback = item_callback

        self._owns_controller = zalo_controller is None
        if zalo_controller is not None:
            self.zalo_controller = zalo_controller
        else:
            self.zalo_controller = ZaloController(log_callback=self.log, qrcode_callback=qrcode_callback, config_manager=config_manager)
        self.upload_queue = UploadQueueManager(
            db_manager=self.db_manager,
            gdrive_service=self.gdrive_service,
            max_workers=self.config_manager.thread_number,
            max_retries=self.config_manager.max_retry,
            status_callback=self.on_queue_status_update,
            log_callback=self.log
        )

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def log(self, level: str, message: str):
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self.log_callback:
            self.log_callback(level, message)

    def on_queue_status_update(self, item: DownloadItem, status_text: str, progress_percent: int):
        if self.item_callback:
            self.item_callback(item, status_text, progress_percent)

    def start(self):
        """Starts the sync loop thread and upload workers."""
        if self.is_running:
            return

        self.is_running = True
        self._stop_event.clear()

        # Start upload workers
        self.upload_queue.start()

        # Launch background loop thread
        self._thread = threading.Thread(target=self._sync_loop, daemon=True, name="ZaloGroupSyncLoop")
        self._thread.start()
        self.log("INFO", "[Sync Engine] Started Zalo PC Group scanner background engine.")

    def stop(self):
        """Stops the sync engine cleanly."""
        if not self.is_running:
            return

        self.is_running = False
        self._stop_event.set()

        if self.upload_queue:
            self.upload_queue.stop()

        # Abort any in-flight bridge command so the loop thread exits quickly
        # instead of waiting for a long timeout (e.g. find_group 120s).
        try:
            if self.zalo_controller:
                if self._owns_controller:
                    self.zalo_controller._running = False
                self.zalo_controller.abort_waiting()
        except Exception:
            pass

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        try:
            if self.zalo_controller and self._owns_controller:
                self.zalo_controller._stop_bridge()
        except Exception:
            pass

        self.log("INFO", "[Sync Engine] Stopped Zalo Group Sync Engine.")

    def _in_schedule_window(self) -> bool:
        if not self.config_manager.schedule_enabled:
            return True
        now = datetime.now()
        start_str = self.config_manager.schedule_start
        end_str = self.config_manager.schedule_end
        try:
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))
            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m
            if start_minutes <= end_minutes:
                return start_minutes <= current_minutes <= end_minutes
            else:
                return current_minutes >= start_minutes or current_minutes <= end_minutes
        except Exception:
            return True

    def run_single_scan(self):
        """Executes one scan cycle: Open Zalo -> Open Group -> Scan Files -> Download & Enqueue Upload."""
        if not self._in_schedule_window():
            self.log("DEBUG", "[Schedule] Outside scheduled window, skipping scan.")
            return

        group_name = self.config_manager.group_name
        download_folder = self.config_manager.download_folder
        download_timeout = self.config_manager.download_timeout
        gdrive_folder_id = self.config_manager.gdrive_folder_id

        if not group_name:
            self.log("ERROR", "[Config] No Zalo group name configured.")
            return

        if not gdrive_folder_id:
            self.log("WARNING", "[Config] Google Drive Folder ID is empty. Files will be downloaded locally but NOT uploaded to Drive. Set it in Settings.")

        # Step 1: Open Zalo
        if not self.zalo_controller.ensure_zalo_running():
            self.log("ERROR", "[Open Zalo] Could not connect to Zalo PC instance.")
            return

        self._scan_single_group(group_name, download_folder, download_timeout, gdrive_folder_id)

    def _scan_single_group(self, group_name: str, download_folder: str,
                           download_timeout: int = 60, gdrive_folder_id: str = ""):
        """Scans and syncs a single Zalo group."""
        self.log("INFO", f"=== Starting scan for group '{group_name}' ===")

        if not self.zalo_controller.open_group(group_name):
            self.log("ERROR", f"[Open Group] Failed to open group '{group_name}'. Group may not exist, not be joined, or Zalo not logged in.")
            return

        group_files: List[GroupFile] = self.zalo_controller.scan_group_files(group_name)
        if not group_files:
            self.log("INFO", f"[Scan Files] No files found in group '{group_name}'.")
            return

        # Step 4: Identify new files using SQLite database (single batched query)
        unprocessed_ids = self.db_manager.filter_unprocessed(
            group_name, [gf.file_id for gf in group_files]
        )
        unprocessed_set = set(unprocessed_ids)
        new_files_count = 0
        for gf in group_files:
            if not self.is_running:
                break

            # Check if already processed in database
            if gf.file_id not in unprocessed_set:
                self.log("DEBUG", f"[SQLite Check] File '{gf.filename}' (ID: {gf.file_id}) already processed. Skipping.")
                continue

            new_files_count += 1
            self.log("INFO", f"[Scan Files] New unhandled file detected: '{gf.filename}' (ID: {gf.file_id}, Size: {gf.filesize / 1024:.1f} KB).")

            # Step 5: Download File from Zalo PC
            local_filepath = self.zalo_controller.download_group_file(
                group_file=gf,
                download_folder=download_folder,
                timeout=download_timeout
            )

            if not local_filepath or not os.path.exists(local_filepath):
                self.log("ERROR", f"[Download File] Failed to confirm download for '{gf.filename}'. Marking failed.")
                item = DownloadItem(
                    filename=gf.filename,
                    filepath="",
                    filesize=gf.filesize,
                    group_name=group_name,
                    message_id=gf.message_id,
                    file_id=gf.file_id,
                    download_status="failed",
                    drive_status="failed",
                    status=SyncStatus.FAILED,
                    error_message="Download timeout or file missing"
                )
                self.db_manager.add_item(item)
                continue

            # Compute hash for duplicate safety
            try:
                file_hash = calculate_sha256(local_filepath)
                actual_size = os.path.getsize(local_filepath)
            except Exception as e:
                file_hash = f"hash_{gf.file_id}"
                actual_size = gf.filesize

            # Check if content already uploaded (hash-based dedup across sessions)
            if self.db_manager.is_file_uploaded(file_hash):
                self.log("INFO", f"[Hash Check] '{gf.filename}' (hash: {file_hash[:8]}...) already uploaded. Skipping.")
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item = DownloadItem(
                    filename=gf.filename,
                    filepath=local_filepath,
                    filesize=actual_size,
                    group_name=group_name,
                    message_id=gf.message_id,
                    file_id=gf.file_id,
                    download_status="downloaded",
                    drive_status="completed",
                    created_time=now_str,
                    last_scan=now_str,
                    status=SyncStatus.COMPLETED,
                    hash=file_hash
                )
                self.db_manager.add_item(item)
                continue

            # Step 6: Create DownloadItem and add to SQLite
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            resume_uri, resume_progress = self.db_manager.get_resumable_state(gf.file_id, group_name)
            item = DownloadItem(
                filename=gf.filename,
                filepath=local_filepath,
                filesize=actual_size,
                group_name=group_name,
                message_id=gf.message_id,
                file_id=gf.file_id,
                download_status="downloaded",
                drive_status="pending",
                created_time=now_str,
                last_scan=now_str,
                status=SyncStatus.PENDING,
                hash=file_hash,
                resumable_uri=resume_uri,
                resumable_progress=resume_progress
            )

            item_id = self.db_manager.add_item(item)
            item.id = item_id

            self.log("INFO", f"[SQLite Update] Logged download for '{gf.filename}' to database (ID: {item_id}). Passing to Upload Queue.")

            # Step 7: Enqueue for Google Drive upload
            if gdrive_folder_id:
                self.upload_queue.add_item(
                    item=item,
                    gdrive_folder_id=gdrive_folder_id,
                    duplicate_action=self.config_manager.get("duplicate_action", "rename")
                )
            else:
                self.log("WARNING", "[Upload Drive] Google Drive folder ID not set. File downloaded locally but skipped Drive upload.")

        if new_files_count == 0:
            self.log("INFO", f"[Scan Files] Scan complete. All {len(group_files)} group files are already synced.")
        else:
            self.log("INFO", f"[Scan Files] Scan complete. Processed {new_files_count} new file(s).")

    def _sync_loop(self):
        """Background loop executing scans at interval."""
        while self.is_running and not self._stop_event.is_set():
            try:
                self.run_single_scan()
            except Exception as e:
                self.log("ERROR", f"[Sync Engine] Error during group scan iteration: {e}")

            interval = max(1, self.config_manager.check_interval)
            # Sleep in small increments to respond quickly to stop event
            slept = 0
            while slept < interval and self.is_running and not self._stop_event.is_set():
                time.sleep(1)
                slept += 1
