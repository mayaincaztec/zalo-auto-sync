"""
Upload Queue Table Widget
Displays real-time progress, file size, status, and control actions for queued uploads.
"""

from typing import Dict, Optional

try:
    from PySide6.QtCore import Qt, Slot
    from PySide6.QtWidgets import (QHeaderView, QLabel, QProgressBar,
                                   QTableWidget, QTableWidgetItem,
                                   QVBoxLayout, QWidget)
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from zalo_drive_sync.database.models import DownloadItem
from zalo_drive_sync.ui.i18n import _TR as _

# Upper bound on table rows so a long-running session doesn't grow UI memory.
_MAX_ROWS = 500
# Columns whose text should be horizontally centered.
_CENTER_COLS = (0, 4, 5)  # ID, Trạng thái, Thử lại


class QueueWidget(QWidget if PYSIDE_AVAILABLE else object):
    """PySide6 Table Widget displaying active upload items and progress."""

    def __init__(self, parent: Optional[QWidget] = None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.item_row_map: Dict[int, int] = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        header_label = QLabel(_["queue_header"])
        header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header_label)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            _["queue_col_id"], _["queue_col_filename"], _["queue_col_size"],
            _["queue_col_progress"], _["queue_col_status"], _["queue_col_retries"]
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 180)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        # Center-align the header text for ID / Trạng thái / Thử lại columns
        for col in _CENTER_COLS:
            header_item = self.table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setTextAlignment(Qt.AlignCenter)

        layout.addWidget(self.table)

    @Slot(object, str, int)
    def update_item_status(self, item: DownloadItem, status_text: str, progress_percent: int):
        """Updates or inserts an item row in the queue table."""
        if not PYSIDE_AVAILABLE or item.id is None:
            return

        if item.id in self.item_row_map:
            row = self.item_row_map[item.id]
        else:
            self._prune_rows()
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.item_row_map[item.id] = row

            id_item = QTableWidgetItem(str(item.id))
            id_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(item.filename))
            size_kb = item.filesize / 1024
            size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
            self.table.setItem(row, 2, QTableWidgetItem(size_str))

            pbar = QProgressBar()
            pbar.setRange(0, 100)
            pbar.setValue(0)
            self.table.setCellWidget(row, 3, pbar)

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, status_item)
            retry_item = QTableWidgetItem(str(item.retry_count))
            retry_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 5, retry_item)

        # Update dynamic fields
        pbar = self.table.cellWidget(row, 3)
        if pbar:
            pbar.setValue(progress_percent)

        status_item = QTableWidgetItem(status_text)
        status_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 4, status_item)
        retry_item = QTableWidgetItem(str(item.retry_count))
        retry_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 5, retry_item)

    def _prune_rows(self):
        """Removes oldest rows when the table reaches _MAX_ROWS."""
        while self.table.rowCount() >= _MAX_ROWS:
            self.table.removeRow(0)
            # Rebuild the id -> row mapping after the top row is dropped.
            new_map = {}
            for fid, r in self.item_row_map.items():
                nr = r - 1
                if nr >= 0:
                    new_map[fid] = nr
            self.item_row_map = new_map
