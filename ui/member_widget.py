"""
Member Stats Widget / Tab
Independent panel for inspecting a Zalo group's member roster, last-active time,
message counts, and optionally kicking inactive members (with confirmation).
"""

import os
import sys
import threading
import time as _time
from typing import List, Optional

# Ensure sys.path contains project root and package directory
_FILE_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_FILE_DIR)
_ROOT_DIR = os.path.dirname(_PACKAGE_DIR)
for _d in (_ROOT_DIR, _PACKAGE_DIR):
    if _d and _d not in sys.path:
        sys.path.insert(0, _d)

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                                   QMessageBox, QPushButton, QTableWidget,
                                   QTableWidgetItem, QVBoxLayout, QWidget)
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.services.zalo_controller import ZaloController
from zalo_drive_sync.ui.i18n import _TR as _


class MemberWidget(QWidget if PYSIDE_AVAILABLE else object):
    """Tab to independently inspect group membership and activity."""

    # Qt signals (thread-safe) — data arrives from a background worker thread.
    members_loaded = Signal(str, list) if PYSIDE_AVAILABLE else None
    members_failed = Signal(str) if PYSIDE_AVAILABLE else None
    kick_finished = Signal(bool, list) if PYSIDE_AVAILABLE else None

    def __init__(self, config_manager: ConfigManager, db_manager: DatabaseManager,
                 zalo_controller: Optional[ZaloController] = None,
                 parent: Optional[QWidget] = None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.config_manager = config_manager
        self.db_manager = db_manager
        self.zalo_controller = zalo_controller
        self._workers: List[threading.Thread] = []
        self._members: list = []
        self._group_id: Optional[str] = None
        if self.members_loaded:
            self.members_loaded.connect(self._on_members_loaded)
            self.members_failed.connect(self._on_members_failed)
            self.kick_finished.connect(self._on_kick_finished)
        self.init_ui()
        self.load_groups()

    # ------------------------------------------------------------------ UI ---
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(_["member_group_label"]))
        self.combo_group = QComboBox()
        self.combo_group.setMinimumContentsLength(30)
        bar.addWidget(self.combo_group, 1)

        bar.addWidget(QLabel(_["member_inactive_label"]))
        self.spin_days = QComboBox()
        for d in (7, 14, 30, 60, 90):
            self.spin_days.addItem(f"{d} {_['day_unit']}", d)
        self.spin_days.setCurrentIndex(2)  # 30 days default
        bar.addWidget(self.spin_days)

        self.btn_load = QPushButton(_["member_load"])
        self.btn_load.clicked.connect(self.load_members)
        bar.addWidget(self.btn_load)

        self.btn_kick = QPushButton(_["member_kick"])
        self.btn_kick.setObjectName("btn_danger")
        self.btn_kick.clicked.connect(self.kick_inactive)
        self.btn_kick.setEnabled(False)
        bar.addWidget(self.btn_kick)
        layout.addLayout(bar)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            _["col_name"], _["col_id"], _["col_role"], _["col_last_active"],
            _["col_msg_count"], _["col_status"],
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet("color: #94A3B8;")
        layout.addWidget(self.lbl_summary)

        hint = QLabel(_["member_hint"])
        hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    # ------------------------------------------------------------- helpers ---
    @staticmethod
    def _now_ts() -> int:
        return int(_time.time())

    @staticmethod
    def _format_ts(ts: int) -> str:
        import datetime
        if not ts:
            return _["never_active"]
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(ts)

    def _days_value(self) -> int:
        return self.spin_days.currentData() or 30

    def _cutoff_ts(self) -> int:
        return self._now_ts() - self._days_value() * 86400

    def clear_table(self):
        self.table.setRowCount(0)

    def load_groups(self):
        self.combo_group.clear()
        for name in self.config_manager.group_names:
            self.combo_group.addItem(name, name)
        if self.combo_group.count() == 0:
            self.combo_group.addItem("")

    # ------------------------------------------------------------- workers ---
    def _start_worker(self, work) -> threading.Thread:
        t = threading.Thread(target=work, daemon=True)
        t.start()
        self._workers = [w for w in self._workers if w.is_alive()] + [t]
        return t

    def _selected_group_id(self) -> Optional[str]:
        name = self.combo_group.currentText().strip()
        if not name or self.zalo_controller is None:
            return None
        if self._group_id:
            return self._group_id
        gid = self.zalo_controller.get_group_id_by_name(name)
        if gid:
            self._group_id = gid
        return gid

    # ------------------------------------------------------------ main flow ----
    def load_members(self):
        if self.zalo_controller is None:
            if self.members_failed:
                self.members_failed.emit("no_controller")
            return
        if not self.combo_group.currentText().strip():
            if self.members_failed:
                self.members_failed.emit("no_group")
            return
        self.btn_load.setEnabled(False)
        self.btn_load.setText(_["member_loading"])
        self.btn_kick.setEnabled(False)

        gid = self._selected_group_id()
        if not gid:
            self.btn_load.setEnabled(True)
            self.btn_load.setText(_["member_load"])
            if self.members_failed:
                self.members_failed.emit("no_group")
            return

        def work():
            try:
                members = self.zalo_controller.get_group_members(gid, 3000)
            except Exception:
                members = []
            if members:
                try:
                    self.db_manager.upsert_members(gid, members)
                except Exception:
                    pass
            if self.members_loaded:
                self.members_loaded.emit(gid, members)

        self._start_worker(work)

    def _on_members_loaded(self, gid: str, members: list):
        try:
            overview = self.db_manager.get_member_activity_overview(gid, self._cutoff_ts())
        except Exception:
            overview = members
        self._render(overview, gid)

    def _on_members_failed(self, reason: str):
        self.btn_load.setEnabled(True)
        self.btn_load.setText(_["member_load"])
        if reason == "no_controller":
            QMessageBox.information(self, _["member_load"], _["login_no_controller"])
        else:
            QMessageBox.warning(self, _["member_load"], _["member_no_group"])

    def _render(self, rows: list, group_id: str):
        self._group_id = group_id
        self._members = list(rows)
        self.clear_table()
        cutoff = self._cutoff_ts()

        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(row.get("name") or _["unknown"])))
            self.table.setItem(r, 1, QTableWidgetItem(str(row.get("id") or "")))
            if row.get("isCreator"):
                role = "👑"
            elif row.get("isAdmin"):
                role = "🛡"
            else:
                role = ""
            self.table.setItem(r, 2, QTableWidgetItem(role))
            last = row.get("lastActive") or 0
            last_item = QTableWidgetItem(self._format_ts(last))
            if last and last < cutoff:
                last_item.setForeground(QColor("#E11D48"))
            self.table.setItem(r, 3, last_item)
            count = QTableWidgetItem(str(row.get("msgCount") or 0))
            count.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 4, count)
            is_inactive = bool(last) and last < cutoff
            status_item = QTableWidgetItem(_["inactive"] if is_inactive else _["active"])
            status_item.setTextAlignment(Qt.AlignCenter)
            if is_inactive:
                status_item.setForeground(QColor("#E11D48"))
            self.table.setItem(r, 5, status_item)

        total = len(rows)
        inactive = sum(1 for m in rows if m.get("lastActive") and m.get("lastActive") < cutoff)
        self.lbl_summary.setText(_["member_summary"].format(total=total, inactive=inactive))
        self.btn_kick.setEnabled(inactive > 0)
        self.btn_load.setEnabled(True)
        self.btn_load.setText(_["member_load"])

    # ------------------------------------------------------------------ kick ---
    def _kick_targets(self):
        cutoff = self._cutoff_ts()
        return [
            m for m in self._members
            if m.get("lastActive") and m.get("lastActive") < cutoff and not m.get("isAdmin")
        ]

    def kick_inactive(self):
        if not self._members or not self._group_id:
            return
        targets = self._kick_targets()
        names = [str(m.get("name") or m.get("id") or "?") for m in targets]
        if not names:
            QMessageBox.information(self, _["kick_title"], _["kick_nothing"])
            return

        skipped = [
            str(m.get("name") or m.get("id") or "?")
            for m in self._members
            if m.get("lastActive") and m.get("lastActive") < self._cutoff_ts() and m.get("isAdmin")
        ]
        extra = ""
        if skipped:
            extra = f"\n\n{_['kick_skip_admins']} {', '.join(skipped)}"

        reply = QMessageBox.question(
            self, _["kick_title"],
            _["kick_confirm"].format(count=len(names), days=self._days_value())
            + "\n\n" + "\n".join(names[:20]) + extra,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        gid = self._group_id

        def work():
            ids = [str(m["id"]) for m in targets]
            failed = []
            if self.zalo_controller:
                try:
                    failed = self.zalo_controller.kick_group_members(gid, ids) or []
                except Exception:
                    failed = ids
            for m in targets:
                st = "error" if str(m.get("id")) in failed else "kicked"
                try:
                    self.db_manager.log_kick(gid, str(m.get("id")), str(m.get("name") or ""),
                                             reason="inactive", status=st)
                except Exception:
                    pass
            if self.kick_finished:
                self.kick_finished.emit(not failed, failed)

        self._start_worker(work)

    def _on_kick_finished(self, ok: bool, failed: list):
        if ok:
            QMessageBox.information(self, _["kick_title"], _["kick_done"])
        else:
            QMessageBox.warning(self, _["kick_title"], _["kick_partial"].format(n=len(failed)))
        self.load_members()