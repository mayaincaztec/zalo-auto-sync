"""
Main Window Module
PySide6 QMainWindow combining Dashboard counters, Queue Table, Live Log Console, and Settings.
"""

import os
import sys
import time
from typing import Optional

# Ensure sys.path contains project root and package directory
_FILE_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_FILE_DIR)
_ROOT_DIR = os.path.dirname(_PACKAGE_DIR)
for _d in (_ROOT_DIR, _PACKAGE_DIR):
    if _d and _d not in sys.path:
        sys.path.insert(0, _d)

try:
    from PySide6.QtCore import QTimer, Qt, Signal
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                                   QMessageBox, QPushButton, QScrollArea,
                                   QSplitter, QTabWidget, QVBoxLayout, QWidget)
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False
from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.core.sync_engine import ZaloGroupSyncEngine
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.database.models import DownloadItem, SyncStatus
from zalo_drive_sync.services.zalo_controller import ZaloController
from zalo_drive_sync.ui.i18n import _TR as _
from zalo_drive_sync.ui.guide_widget import GuideWidget
from zalo_drive_sync.ui.log_widget import LogWidget
from zalo_drive_sync.ui.member_widget import MemberWidget
from zalo_drive_sync.ui.queue_widget import QueueWidget
from zalo_drive_sync.ui.settings_dialog import SettingsWidget
from zalo_drive_sync.ui.styles import get_stylesheet
from zalo_drive_sync.ui.tray_icon import AppTrayIcon

_TRAY_NOTIFY_DEBOUNCE_S = 5.0


class MainWindow(QMainWindow if PYSIDE_AVAILABLE else object):
    """Main window for downloading Zalo group files to a local folder."""

    # Custom Qt Signals for thread safety
    log_signal = Signal(str, str) if PYSIDE_AVAILABLE else None
    item_status_signal = Signal(object, str, int) if PYSIDE_AVAILABLE else None
    qrcode_signal = Signal(str) if PYSIDE_AVAILABLE else None
    tray_notify_signal = Signal(str, str, bool) if PYSIDE_AVAILABLE else None
    login_state_signal = Signal(bool) if PYSIDE_AVAILABLE else None

    def __init__(
        self,
        config_manager: ConfigManager,
        db_manager: DatabaseManager,
    ):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__()

        self.config_manager = config_manager
        self.db_manager = db_manager

        self.is_syncing = False
        self.sync_engine: Optional[ZaloGroupSyncEngine] = None
        self._completed_count = 0
        self._last_tray_notify = 0.0
        self.zalo_controller = ZaloController(
            log_callback=self.emit_log,
            qrcode_callback=self._on_qr_ready,
            config_manager=self.config_manager
        )

        self.setWindowTitle(_["window_title"])
        try:
            from PySide6.QtGui import QIcon
            from zalo_drive_sync.utils.resources import icon_ico_path
            self.setWindowIcon(QIcon(icon_ico_path()))
        except Exception:
            pass
        self.resize(1000, 680)

        self.init_ui()
        self.init_signals()
        self.apply_theme()
        self.init_tray()
        self.refresh_stats()

        # Debounce DB stat refreshes to avoid jank when many items update at once.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self.refresh_stats)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Header Bar
        header_frame = QFrame()
        header_frame.setObjectName("header_bar")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(12)

        # App brand: icon + title/subtitle
        try:
            from PySide6.QtGui import QPixmap
            from zalo_drive_sync.utils.resources import icon_png_path
            brand_icon = QLabel()
            pixmap = QPixmap(icon_png_path())
            if not pixmap.isNull():
                brand_icon.setPixmap(pixmap.scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                brand_icon.setFixedSize(34, 34)
                brand_icon.setObjectName("brand_icon")
            else:
                brand_icon = None
        except Exception:
            brand_icon = None

        brand_box = QWidget()
        brand_layout = QVBoxLayout(brand_box)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(0)

        title_label = QLabel(_["title_label"])
        title_label.setObjectName("brand_title")

        subtitle_label = QLabel(_["brand_subtitle"])
        subtitle_label.setObjectName("brand_subtitle")

        brand_layout.addWidget(title_label)
        brand_layout.addWidget(subtitle_label)

        if brand_icon is not None:
            header_layout.addWidget(brand_icon)
        header_layout.addWidget(brand_box)
        header_layout.addStretch()

        self.lbl_sync_status = QLabel(_["sync_stopped"])
        self.lbl_sync_status.setObjectName("sync_status")
        self.lbl_sync_status.setProperty("state", "stopped")
        self.lbl_sync_status.setAlignment(Qt.AlignCenter)

        # Button menu (segmented control): Connect Zalo | Sync now | Start/Stop
        menu_frame = QFrame()
        menu_frame.setObjectName("btn_menu")
        menu_layout = QHBoxLayout(menu_frame)
        menu_layout.setContentsMargins(4, 4, 4, 4)
        menu_layout.setSpacing(4)

        self.btn_login_zalo = QPushButton(_["btn_login_zalo"])
        self.btn_login_zalo.setObjectName("btn_menu_login")
        self.btn_login_zalo.setProperty("menuBtn", True)
        self.btn_login_zalo.setProperty("connected", False)
        self.btn_login_zalo.setCursor(Qt.PointingHandCursor)
        self.btn_login_zalo.setToolTip(_["menu_tip_login"])
        self.btn_login_zalo.clicked.connect(self.login_zalo)

        self.btn_sync_now = QPushButton(_["dash_btn_sync_now"])
        self.btn_sync_now.setObjectName("btn_menu_sync")
        self.btn_sync_now.setProperty("menuBtn", True)
        self.btn_sync_now.setCursor(Qt.PointingHandCursor)
        self.btn_sync_now.setToolTip(_["menu_tip_sync_now"])
        self.btn_sync_now.clicked.connect(self.sync_now)

        self.btn_toggle_sync = QPushButton(_["btn_start"])
        self.btn_toggle_sync.setObjectName("btn_menu_stop")
        self.btn_toggle_sync.setProperty("menuBtn", True)
        self.btn_toggle_sync.setProperty("active", False)
        self.btn_toggle_sync.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_sync.setToolTip(_["menu_tip_toggle"])
        self.btn_toggle_sync.clicked.connect(self.toggle_sync)

        menu_layout.addWidget(self.btn_login_zalo)
        menu_layout.addWidget(self.btn_sync_now)
        menu_layout.addWidget(self.btn_toggle_sync)

        header_layout.addWidget(self.lbl_sync_status)
        header_layout.addWidget(menu_frame)

        main_layout.addWidget(header_frame)

        # Dashboard Counter Cards
        cards_layout = QHBoxLayout()

        self.card_total = self._create_stat_card(_["card_total"], "0 " + _["dash_files"])
        self.card_uploaded = self._create_stat_card(_["card_uploaded"], "0 " + _["dash_files"])
        self.card_errors = self._create_stat_card(_["card_errors"], "0 " + _["dash_files"])
        self.card_size = self._create_stat_card(_["card_size"], "0 MB")

        cards_layout.addWidget(self.card_total["widget"])
        cards_layout.addWidget(self.card_uploaded["widget"])
        cards_layout.addWidget(self.card_errors["widget"])
        cards_layout.addWidget(self.card_size["widget"])

        main_layout.addLayout(cards_layout)

        # Tabs Widget
        self.tabs = QTabWidget()

        self.queue_widget = QueueWidget()
        self.log_widget = LogWidget()
        self.settings_widget = SettingsWidget(self.config_manager, zalo_controller=self.zalo_controller)
        self.settings_widget.settings_saved.connect(self.on_settings_saved)
        # Closing the QR dialog after a successful login is shared across both
        # entry points (header button and Settings tab).
        self.settings_widget.login_done.connect(self._on_login_state)
        self.settings_widget.quit_requested.connect(self._quit_after_update)

        activity_splitter = QSplitter(Qt.Orientation.Vertical)
        activity_splitter.addWidget(self.queue_widget)
        activity_splitter.addWidget(self.log_widget)
        activity_splitter.setStretchFactor(0, 3)
        activity_splitter.setStretchFactor(1, 2)
        activity_splitter.setSizes([420, 280])
        activity_splitter.setChildrenCollapsible(False)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; } "
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        settings_scroll.setWidget(self.settings_widget)

        self.tabs.addTab(activity_splitter, _["tab_activity"])
        self.tabs.addTab(settings_scroll, _["tab_settings"])
        self.guide_widget = GuideWidget()
        self.tabs.addTab(self.guide_widget, _["tab_guide"])

        self.member_widget = MemberWidget(
            self.config_manager, self.db_manager, zalo_controller=self.zalo_controller)
        self.tabs.addTab(self.member_widget, _["tab_members"])

        main_layout.addWidget(self.tabs)

    def _create_stat_card(self, title: str, default_val: str):
        card = QFrame()
        card.setObjectName("stat_card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("stat_card_title")

        lbl_value = QLabel(default_val)
        lbl_value.setObjectName("stat_card_value")

        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_value)

        return {"widget": card, "val_label": lbl_value}

    def init_signals(self):
        if self.log_signal:
            self.log_signal.connect(self.log_widget.append_log)
        if self.qrcode_signal:
            self.qrcode_signal.connect(self._show_qr_dialog)
        if self.item_status_signal:
            self.item_status_signal.connect(self.queue_widget.update_item_status)
        if self.tray_notify_signal:
            self.tray_notify_signal.connect(self._on_tray_notify)
        if self.login_state_signal:
            self.login_state_signal.connect(self._on_login_state)

    def _on_tray_notify(self, title: str, message: str, is_error: bool):
        self.tray_icon.notify(title, message, is_error)

    def apply_theme(self):
        self.setStyleSheet(get_stylesheet("dark"))

    def init_tray(self):
        self.tray_icon = AppTrayIcon(
            parent=self,
            on_toggle_sync=self.toggle_sync,
            on_open_app=self.show_normal_and_raise,
            on_exit_app=self.force_exit
        )
        self.tray_icon.show()

    def show_normal_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def refresh_stats(self):
        """Updates dashboard counter card labels from database."""
        stats = self.db_manager.get_stats()
        self.card_total["val_label"].setText(f"{stats['total_files']} " + _["dash_files"])
        self.card_uploaded["val_label"].setText(f"{stats['downloaded_files']} " + _["dash_files"])
        self.card_errors["val_label"].setText(f"{stats['error_files']} " + _["dash_files"])

        mb = stats['total_bytes'] / (1024 * 1024)
        if mb > 1024:
            self.card_size["val_label"].setText(f"{mb / 1024:.2f} GB")
        else:
            self.card_size["val_label"].setText(f"{mb:.1f} MB")

    def _reapply_status_style(self):
        self.lbl_sync_status.style().unpolish(self.lbl_sync_status)
        self.lbl_sync_status.style().polish(self.lbl_sync_status)

    def sync_now(self):
        if not self.is_syncing:
            self.start_sync()
            return
        # Already running: run one extra scan off the UI thread so the window
        # stays responsive while the scan (find_group, downloads) executes.
        engine = getattr(self, "sync_engine", None)
        if engine is None:
            return
        import threading

        def work():
            try:
                engine.run_single_scan()
            except Exception as e:
                self.emit_log("ERROR", f"[Sync] {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_qr_ready(self, path: str):
        if self.qrcode_signal:
            self.qrcode_signal.emit(path)

    def _show_qr_dialog(self, path: str):
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
            from PySide6.QtGui import QPixmap
            from PySide6.QtCore import Qt
            if hasattr(self, "_qr_dialog") and self._qr_dialog is not None:
                try:
                    self._qr_dialog.close()
                    self._qr_dialog.deleteLater()
                except Exception:
                    pass
            dialog = QDialog(self)
            dialog.setWindowTitle(_["qr_title"])
            dialog.resize(320, 360)
            layout = QVBoxLayout(dialog)
            label = QLabel()
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                label.setText(f"QR: {path}")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
            hint = QLabel(_["qr_hint"])
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color: #666;")
            layout.addWidget(hint)
            dialog.setModal(False)
            dialog.show()
            self._qr_dialog = dialog
            dialog.finished.connect(self._on_qr_dialog_closed)
        except Exception as e:
            self.emit_log("ERROR", f"QR dialog error: {e}")

    def _on_qr_dialog_closed(self, *_):
        self._qr_dialog = None

    def login_zalo(self):
        """Logs into Zalo (QR or saved session) without starting sync."""
        import threading
        self.btn_login_zalo.setEnabled(False)
        self.btn_login_zalo.setText(_["login_connecting"])
        controller = self.zalo_controller

        def work():
            try:
                ok = controller.ensure_zalo_running()
            except Exception:
                ok = False
            if self.login_state_signal:
                self.login_state_signal.emit(ok)

        threading.Thread(target=work, daemon=True).start()

    def _on_login_state(self, ok: bool):
        self.btn_login_zalo.setEnabled(True)
        if ok:
            self.btn_login_zalo.setText(_["login_connected"])
            self.btn_login_zalo.setProperty("connected", True)
            self.emit_log("INFO", _["login_connected"])
        else:
            self.btn_login_zalo.setText(_["btn_login_zalo"])
            self.btn_login_zalo.setProperty("connected", False)
            self.emit_log("ERROR", _["login_failed"])
        self.btn_login_zalo.style().unpolish(self.btn_login_zalo)
        self.btn_login_zalo.style().polish(self.btn_login_zalo)
        if hasattr(self, "_qr_dialog") and self._qr_dialog is not None:
            try:
                self._qr_dialog.close()
            except Exception:
                pass
        if hasattr(self, "settings_widget") and self.settings_widget:
            self.settings_widget.set_login_state(ok)

    def toggle_sync(self):
        if self.is_syncing:
            self.stop_sync()
        else:
            self.start_sync()

    def start_sync(self):
        group_names = self.config_manager.group_names
        download_folder = self.config_manager.download_folder

        if not download_folder:
            QMessageBox.warning(self, _["missing_folder_title"], _["missing_folder_msg"])
            self.tabs.setCurrentIndex(1)
            return

        if not group_names:
            QMessageBox.warning(self, _["missing_group_title"], _["missing_group_msg"])
            self.tabs.setCurrentIndex(1)
            return

        group_summary = ", ".join(group_names)
        self.emit_log("INFO", _["log_initializing"].format(group_summary))

        self._completed_count = 0

        self.sync_engine = ZaloGroupSyncEngine(
            config_manager=self.config_manager,
            db_manager=self.db_manager,
            log_callback=self.emit_log,
            item_callback=self.on_queue_status_update,
            qrcode_callback=self._on_qr_ready,
            zalo_controller=self.zalo_controller
        )
        self.sync_engine.start()

        self.is_syncing = True
        self.lbl_sync_status.setText(_["sync_active"])
        self.lbl_sync_status.setProperty("state", "active")
        self._reapply_status_style()
        self.btn_toggle_sync.setText(_["btn_stop"])
        self.btn_toggle_sync.setProperty("active", True)
        self.btn_toggle_sync.style().unpolish(self.btn_toggle_sync)
        self.btn_toggle_sync.style().polish(self.btn_toggle_sync)
        self.tray_icon.update_sync_state(True)
        self.tray_icon.notify(_["tray_sync_active"], _["tray_sync_msg"].format(group_summary))

    def stop_sync(self):
        if hasattr(self, 'sync_engine') and self.sync_engine:
            self.sync_engine.stop()
            self.sync_engine = None

        self.is_syncing = False
        self.lbl_sync_status.setText(_["sync_stopped"])
        self.lbl_sync_status.setProperty("state", "stopped")
        self._reapply_status_style()
        self.btn_toggle_sync.setText(_["btn_start"])
        self.btn_toggle_sync.setProperty("active", False)
        self.btn_toggle_sync.style().unpolish(self.btn_toggle_sync)
        self.btn_toggle_sync.style().polish(self.btn_toggle_sync)
        self.tray_icon.update_sync_state(False)
        self.emit_log("INFO", _["log_stopped_sync"])

    def on_queue_status_update(self, item: DownloadItem, status_text: str, progress_percent: int):
        if self.item_status_signal:
            self.item_status_signal.emit(item, status_text, progress_percent)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()
        if item.status == SyncStatus.COMPLETED:
            self._completed_count += 1
            # Debounce tray popups: batch rapid completions into one notification
            now = time.monotonic()
            if now - self._last_tray_notify >= _TRAY_NOTIFY_DEBOUNCE_S:
                self._last_tray_notify = now
                if self.tray_notify_signal:
                    self.tray_notify_signal.emit(_["tray_new_file"], _["tray_new_file_msg"].format(item.filename), False)

    def emit_log(self, level: str, message: str):
        if self.log_signal:
            self.log_signal.emit(level, message)

    def on_settings_saved(self):
        self.apply_theme()
        if self.is_syncing:
            self.emit_log("INFO", _["log_settings_restart"])
            self.stop_sync()
            self.start_sync()

    def _quit_after_update(self):
        """Called after an update is staged: stops everything and exits the app."""
        self.force_exit()
        if PYSIDE_AVAILABLE:
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    def closeEvent(self, event: QCloseEvent):
        """Minimize to system tray on window close button."""
        if self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.notify(_["tray_background_title"], _["tray_background_msg"])
            event.ignore()
            return
        event.accept()

    def force_exit(self):
        """Full exit from tray menu: hide tray, stop bridge, then close window."""
        self.stop_sync()
        try:
            if self.zalo_controller:
                self.zalo_controller._stop_bridge()
        except Exception:
            pass
        if self.tray_icon:
            self.tray_icon.hide()
        if PYSIDE_AVAILABLE:
            self.close()
