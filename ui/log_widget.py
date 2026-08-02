"""
Log Viewer Widget
PySide6 widget displaying live log outputs with colorized levels and search filter.
"""

from typing import Optional

try:
    from PySide6.QtCore import QTimer, Slot
    from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                                   QPlainTextEdit, QPushButton, QVBoxLayout,
                                   QWidget)
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from zalo_drive_sync.ui.i18n import _TR as _

_MAX_LINES = 5000
_FLUSH_MS = 120


class LogWidget(QWidget if PYSIDE_AVAILABLE else object):
    """Log Console Widget for PySide6 application."""

    _LEVEL_COLORS = {
        "ERROR": "#EF4444",
        "WARN": "#F59E0B",
        "INFO": "#10B981",
    }

    def __init__(self, parent: Optional[QWidget] = None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self._pending = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_MS)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_pending)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        header_layout = QHBoxLayout()
        header_label = QLabel(_["log_header"])
        header_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(_["log_filter"])
        self.search_input.textChanged.connect(self.filter_logs)

        btn_clear = QPushButton(_["btn_clear_logs"])
        btn_clear.setObjectName("btn_secondary")
        btn_clear.clicked.connect(self.clear_logs)

        header_layout.addWidget(header_label)
        header_layout.addStretch()
        header_layout.addWidget(self.search_input)
        header_layout.addWidget(btn_clear)

        layout.addLayout(header_layout)

        self.log_text_edit = QPlainTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setMaximumBlockCount(_MAX_LINES)
        layout.addWidget(self.log_text_edit)

        self.all_log_lines = []

    def _format_char(self, level_str: str) -> QTextCharFormat:
        char_format = QTextCharFormat()
        color = self._LEVEL_COLORS.get(level_str, "#94A3B8")
        char_format.setForeground(QColor(color))
        return char_format

    @Slot(str, str)
    def append_log(self, level: str, message: str):
        """Queues a log line; batched flush to avoid UI jank."""
        if not PYSIDE_AVAILABLE:
            return
        level_str = level.upper()
        self.all_log_lines.append((level_str, message))
        if len(self.all_log_lines) > _MAX_LINES:
            del self.all_log_lines[:len(self.all_log_lines) - _MAX_LINES]
        self._pending.append((level_str, message))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self):
        if not self._pending:
            return
        filter_text = self.search_input.text().lower()
        cursor = self.log_text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        buffer = []
        for level_str, message in self._pending:
            log_line = f"[{level_str}] {message}"
            if filter_text and filter_text not in log_line.lower():
                continue
            buffer.append((log_line, level_str))
        self._pending = []
        self.log_text_edit.setUpdatesEnabled(False)
        try:
            for log_line, level_str in buffer:
                cursor.insertText(f"{log_line}\n", self._format_char(level_str))
        finally:
            self.log_text_edit.setUpdatesEnabled(True)
        # Always keep the view pinned to the newest line.
        self.log_text_edit.setTextCursor(cursor)
        sb = self.log_text_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def filter_logs(self, text: str):
        """Refreshes visible log lines according to filter string."""
        self.log_text_edit.clear()
        filter_lower = text.lower()
        self.log_text_edit.setUpdatesEnabled(False)
        try:
            cursor = self.log_text_edit.textCursor()
            cursor.movePosition(QTextCursor.End)
            for level_str, message in self.all_log_lines:
                log_line = f"[{level_str}] {message}"
                if not filter_lower or filter_lower in log_line.lower():
                    cursor.insertText(f"{log_line}\n", self._format_char(level_str))
        finally:
            self.log_text_edit.setUpdatesEnabled(True)
        self.log_text_edit.setTextCursor(cursor)
        self.log_text_edit.verticalScrollBar().setValue(
            self.log_text_edit.verticalScrollBar().maximum())

    def clear_logs(self):
        self.log_text_edit.clear()
        self.all_log_lines.clear()
        self._pending.clear()
