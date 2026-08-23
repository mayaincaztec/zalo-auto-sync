"""
Zalo Group local download engine.

Workflow:
Open Zalo -> Open Group -> Scan Group Files -> Identify New Files via SQLite ->
Download directly to the configured local folder -> Update SQLite history.

The destination may be a OneDrive/SharePoint-synced folder. Cloud replication
is intentionally delegated to the OneDrive desktop client.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.core.hasher import calculate_sha256
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.zalo_controller import GroupFile, ZaloController

logger = logging.getLogger("ZaloPCSync")


def resolve_local_destination(
    download_folder: str,
    filename: str,
    duplicate_action: str = "rename",
) -> Optional[str]:
    """Returns a safe destination path for a Zalo attachment.

    ``rename`` creates ``name (1).ext`` without overwriting an existing file,
    ``overwrite`` reuses the existing path, and ``skip`` returns ``None``.
    """
    folder = os.path.abspath(download_folder)
    os.makedirs(folder, exist_ok=True)

    safe_name = os.path.basename((filename or "").strip()) or "zalo_file"
    destination = os.path.join(folder, safe_name)

    if not os.path.exists(destination) or duplicate_action == "overwrite":
        return destination
    if duplicate_action == "skip":
        return None

    stem, extension = os.path.splitext(safe_name)
    counter = 1
    while True:
        candidate = os.path.join(folder, f"{stem} ({counter}){extension}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


class ZaloGroupSyncEngine:
    """Scans selected Zalo groups and downloads new files to a local folder."""

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: DatabaseManager,
        log_callback: Optional[Callable[[str, str], None]] = None,
        item_callback: Optional[Callable[[DownloadItem, str, int], None]] = None,
        qrcode_callback: Optional[Callable[[str], None]] = None,
        zalo_controller: Optional[ZaloController] = None,
    ):
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.log_callback = log_callback
        self.item_callback = item_callback

        self._owns_controller = zalo_controller is None
        if zalo_controller is not None:
            self.zalo_controller = zalo_controller
        else:
            self.zalo_controller = ZaloController(
                log_callback=self.log,
                qrcode_callback=qrcode_callback,
                config_manager=config_manager,
            )

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def log(self, level: str, message: str):
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self.log_callback:
            self.log_callback(level, message)

    def on_item_status_update(
        self, item: DownloadItem, status_text: str, progress_percent: int
    ):
        if self.item_callback:
            self.item_callback(item, status_text, progress_percent)

    # Compatibility alias for older callers.
    def on_queue_status_update(
        self, item: DownloadItem, status_text: str, progress_percent: int
    ):
        self.on_item_status_update(item, status_text, progress_percent)

    def start(self):
        """Starts the local download loop in a background thread."""
        if self.is_running:
            return

        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sync_loop,
            daemon=True,
            name="ZaloGroupDownloadLoop",
        )
        self._thread.start()
        self.log("INFO", "[Download Engine] Started Zalo group scanner.")

    def stop(self):
        """Stops the engine cleanly."""
        if not self.is_running:
            return

        self.is_running = False
        self._stop_event.set()

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

        self.log("INFO", "[Download Engine] Stopped Zalo group scanner.")

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
            return current_minutes >= start_minutes or current_minutes <= end_minutes
        except Exception:
            return True

    def run_single_scan(self):
        """Runs one scan across every selected Zalo group."""
        group_names = self.config_manager.group_names
        download_folder = self.config_manager.download_folder
        download_timeout = self.config_manager.download_timeout

        if not group_names:
            self.log("ERROR", "[Config] No Zalo groups configured.")
            return
        if not download_folder:
            self.log("ERROR", "[Config] No local download folder configured.")
            return
        try:
            os.makedirs(download_folder, exist_ok=True)
        except OSError as exc:
            self.log("ERROR", f"[Config] Cannot access local download folder: {exc}")
            return

        if not self.zalo_controller.ensure_zalo_running():
            self.log("ERROR", "[Open Zalo] Could not connect to Zalo PC instance.")
            return

        self.log("INFO", f"[Groups] Scanning {len(group_names)} selected group(s).")
        for group_name in group_names:
            if self._stop_event.is_set():
                break
            self._scan_single_group(group_name, download_folder, download_timeout)

    def _seconds_until_next_daily_run(self, now: Optional[datetime] = None) -> float:
        """Returns seconds until the next configured daily run (1-3 times)."""
        current = now or datetime.now()
        candidates = []
        for text in self.config_manager.daily_times:
            hour, minute = map(int, text.split(":"))
            candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= current:
                candidate += timedelta(days=1)
            candidates.append(candidate)
        next_run = min(candidates)
        return max(1.0, (next_run - current).total_seconds())

    def _record_skipped(
        self,
        group_file: GroupFile,
        group_name: str,
        existing_path: str,
    ):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item = DownloadItem(
            filename=group_file.filename,
            filepath=existing_path,
            filesize=(os.path.getsize(existing_path) if os.path.exists(existing_path) else group_file.filesize),
            group_name=group_name,
            message_id=group_file.message_id,
            file_id=group_file.file_id,
            download_status="skipped",
            drive_status="not_required",
            created_time=now_str,
            uploaded_time=now_str,
            last_scan=now_str,
            status=SyncStatus.SKIPPED,
        )
        item.id = self.db_manager.add_item(item)
        self.on_item_status_update(item, "Đã bỏ qua (trùng tên)", 100)

    def _record_failed(self, group_file: GroupFile, group_name: str):
        item = DownloadItem(
            filename=group_file.filename,
            filepath="",
            filesize=group_file.filesize,
            group_name=group_name,
            message_id=group_file.message_id,
            file_id=group_file.file_id,
            download_status="failed",
            drive_status="not_required",
            status=SyncStatus.FAILED,
            error_message="Download timeout or file missing",
        )
        item.id = self.db_manager.add_item(item)
        self.on_item_status_update(item, "Tải xuống thất bại", 0)

    def _scan_single_group(
        self,
        group_name: str,
        download_folder: str,
        download_timeout: int = 60,
    ):
        """Scans one group and saves every new attachment locally."""
        self.log("INFO", f"=== Starting scan for group '{group_name}' ===")

        if not self.zalo_controller.open_group(group_name):
            self.log(
                "ERROR",
                f"[Open Group] Failed to open group '{group_name}'. Group may not exist, not be joined, or Zalo not logged in.",
            )
            return

        group_files: List[GroupFile] = self.zalo_controller.scan_group_files(group_name)
        if not group_files:
            self.log("INFO", f"[Scan Files] No files found in group '{group_name}'.")
            return

        unprocessed_ids = self.db_manager.filter_unprocessed(
            group_name, [group_file.file_id for group_file in group_files]
        )
        unprocessed_set = set(unprocessed_ids)
        new_files_count = 0
        duplicate_action = self.config_manager.get("duplicate_action", "rename")

        for group_file in group_files:
            if not self.is_running:
                break

            if group_file.file_id not in unprocessed_set:
                self.log(
                    "DEBUG",
                    f"[SQLite Check] File '{group_file.filename}' (ID: {group_file.file_id}) already processed. Skipping.",
                )
                continue

            new_files_count += 1
            self.log(
                "INFO",
                f"[Scan Files] New file: '{group_file.filename}' (ID: {group_file.file_id}, Size: {group_file.filesize / 1024:.1f} KB).",
            )

            destination = resolve_local_destination(
                download_folder,
                group_file.filename,
                duplicate_action,
            )
            if destination is None:
                existing_path = os.path.join(
                    os.path.abspath(download_folder),
                    os.path.basename(group_file.filename),
                )
                self.log("INFO", f"[Local File] '{group_file.filename}' already exists. Skipped by policy.")
                self._record_skipped(group_file, group_name, existing_path)
                continue

            local_filepath = self.zalo_controller.download_group_file(
                group_file=group_file,
                download_folder=download_folder,
                timeout=download_timeout,
                destination_path=destination,
            )

            if not local_filepath or not os.path.exists(local_filepath):
                self.log(
                    "ERROR",
                    f"[Download File] Failed to confirm download for '{group_file.filename}'.",
                )
                self._record_failed(group_file, group_name)
                continue

            try:
                file_hash = calculate_sha256(local_filepath)
                actual_size = os.path.getsize(local_filepath)
            except Exception:
                file_hash = f"hash_{group_file.file_id}"
                actual_size = group_file.filesize

            content_was_seen = self.db_manager.is_file_downloaded(file_hash)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item = DownloadItem(
                filename=os.path.basename(local_filepath),
                filepath=local_filepath,
                filesize=actual_size,
                group_name=group_name,
                message_id=group_file.message_id,
                file_id=group_file.file_id,
                download_status="downloaded",
                drive_status="not_required",
                created_time=now_str,
                uploaded_time=now_str,
                last_scan=now_str,
                status=SyncStatus.COMPLETED,
                hash=file_hash,
            )
            item.id = self.db_manager.add_item(item)

            if content_was_seen:
                status_text = "Đã tải xuống (nội dung trùng)"
                self.log("INFO", f"[Hash Check] '{item.filename}' matches previously downloaded content.")
            else:
                status_text = "Đã tải xuống"

            self.on_item_status_update(item, status_text, 100)
            self.log("INFO", f"[Local Download] Saved '{item.filename}' to '{local_filepath}'.")

        if new_files_count == 0:
            self.log(
                "INFO",
                f"[Scan Files] Scan complete. All {len(group_files)} group files are already downloaded.",
            )
        else:
            self.log("INFO", f"[Scan Files] Scan complete. Processed {new_files_count} new file(s).")

    def _sync_loop(self):
        while self.is_running and not self._stop_event.is_set():
            mode = self.config_manager.auto_schedule_mode
            if mode == "daily":
                wait_seconds = self._seconds_until_next_daily_run()
                next_minutes = max(1, int(round(wait_seconds / 60)))
                self.log("INFO", f"[Schedule] Next daily scan in about {next_minutes} minute(s).")
                if self._stop_event.wait(wait_seconds):
                    break

            try:
                self.run_single_scan()
            except Exception as exc:
                self.log("ERROR", f"[Download Engine] Error during group scan: {exc}")

            if mode == "interval":
                interval = max(1, self.config_manager.check_interval)
                self.log("INFO", f"[Schedule] Next scan in {self.config_manager.auto_interval_hours} hour(s).")
                if self._stop_event.wait(interval):
                    break
