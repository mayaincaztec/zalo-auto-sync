"""
Settings Widget / Tab
PySide6 settings interface for modifying download directory, Google Drive ID, extensions, and intervals.
"""

import io
import json
import os
import zipfile
from typing import Optional

try:
    from PySide6.QtCore import QThread, Signal, QTime
    from PySide6.QtGui import QIntValidator
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
                                   QFormLayout, QGridLayout, QGroupBox,
                                   QHBoxLayout, QLabel, QLineEdit,
                                   QMessageBox, QPushButton, QTimeEdit,
                                   QVBoxLayout, QWidget)
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.services.zalo_controller import ZaloController
from zalo_drive_sync.ui.i18n import _TR as _
from zalo_drive_sync.utils.startup import (is_auto_start_enabled,
                                            set_auto_start)

# Shared style for small grey helper/hint labels
_HINT_STYLE = "color: #94A3B8; font-size: 11px; font-weight: 600;"
_HINT_STYLE_NO_BOLD = "color: #94A3B8; font-size: 11px;"
_DEFAULT_TIMEOUT = 300
_TIMEOUT_MIN = 10
_TIMEOUT_MAX = 600


class SettingsWidget(QWidget if PYSIDE_AVAILABLE else object):
    """PySide6 Settings tab for user configuration."""

    settings_saved = Signal() if PYSIDE_AVAILABLE else None
    groups_loaded = Signal(list) if PYSIDE_AVAILABLE else None
    groups_error = Signal(str) if PYSIDE_AVAILABLE else None
    login_done = Signal(bool) if PYSIDE_AVAILABLE else None
    update_found = Signal(dict) if PYSIDE_AVAILABLE else None
    update_downloaded = Signal(str) if PYSIDE_AVAILABLE else None
    update_failed = Signal(str) if PYSIDE_AVAILABLE else None
    quit_requested = Signal() if PYSIDE_AVAILABLE else None

    def __init__(self, config_manager: ConfigManager,
                 zalo_controller: Optional[ZaloController] = None,
                 parent: Optional[QWidget] = None):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)
        self.config_manager = config_manager
        self.zalo_controller = zalo_controller
        self._group_names: list = []
        self._group_worker = None
        self._login_worker = None
        self._login_ok = False
        self.groups_loaded.connect(self._on_groups_loaded)
        self.groups_error.connect(self._on_groups_error)
        self.login_done.connect(self._on_login_done)
        self.update_found.connect(self._on_update_found)
        self.update_downloaded.connect(self._on_update_downloaded)
        self.update_failed.connect(self._on_update_failed)
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        # Group 1: Zalo PC & Directory
        folder_group = QGroupBox(_["settings_zalo_group"])
        folder_layout = QFormLayout(folder_group)

        self.combo_group_name = QComboBox()
        self.combo_group_name.setEditable(True)
        self.combo_group_name.setInsertPolicy(QComboBox.NoInsert)
        self.combo_group_name.setPlaceholderText(_["settings_group_placeholder"])
        self.combo_group_name.setMinimumContentsLength(30)
        self.combo_group_name.activated.connect(self._on_group_selected)

        btn_login_zalo = QPushButton(_["btn_login_zalo"])
        btn_login_zalo.setObjectName("btn_secondary")
        btn_login_zalo.clicked.connect(self._on_connect_clicked)
        self.btn_login_zalo = btn_login_zalo

        group_hbox = QHBoxLayout()
        group_hbox.addWidget(self.combo_group_name, 1)
        group_hbox.addWidget(btn_login_zalo)

        folder_layout.addRow(_["settings_group_name"], group_hbox)

        self.txt_download_folder = QLineEdit()
        btn_browse = QPushButton(_["btn_browse"])
        btn_browse.setObjectName("btn_secondary")
        btn_browse.clicked.connect(self.browse_folder)

        folder_hbox = QHBoxLayout()
        folder_hbox.addWidget(self.txt_download_folder)
        folder_hbox.addWidget(btn_browse)

        folder_layout.addRow(_["settings_folder"], folder_hbox)

        self.txt_download_timeout = QLineEdit()
        self.txt_download_timeout.setText(str(_DEFAULT_TIMEOUT))
        self.txt_download_timeout.setValidator(QIntValidator(_TIMEOUT_MIN, _TIMEOUT_MAX))
        self.txt_download_timeout.setPlaceholderText(str(_DEFAULT_TIMEOUT))
        folder_layout.addRow(_["settings_timeout"], self.txt_download_timeout)

        self.txt_gdrive_folder = QLineEdit()
        self.txt_gdrive_folder.setPlaceholderText(_["settings_gdrive_placeholder"])
        folder_layout.addRow(_["settings_gdrive_id"], self.txt_gdrive_folder)

        layout.addWidget(folder_group)

        # Group 2: Filter & Strategy
        filter_group = QGroupBox(_["settings_filter"])
        filter_layout = QFormLayout(filter_group)

        self.txt_extensions = QLineEdit()
        self.txt_extensions.setPlaceholderText(_["settings_ext_placeholder"])
        filter_layout.addRow(_["settings_extensions"], self.txt_extensions)

        dup_row = QHBoxLayout()
        self.chk_dup_rename = QCheckBox(_["dup_rename"])
        self.chk_dup_skip = QCheckBox(_["dup_skip"])
        self.chk_dup_overwrite = QCheckBox(_["dup_overwrite"])
        for chk in (self.chk_dup_rename, self.chk_dup_skip, self.chk_dup_overwrite):
            chk.setObjectName("dup_check")
            chk.toggled.connect(self._on_dup_toggled)
            dup_row.addWidget(chk)
        dup_row.addStretch()
        filter_layout.addRow(_["settings_duplicate"], dup_row)

        layout.addWidget(filter_group)

        # Group 3: Performance & System
        perf_group = QGroupBox(_["settings_perf"])
        perf_grid = QGridLayout(perf_group)
        perf_grid.setContentsMargins(12, 16, 12, 12)
        perf_grid.setHorizontalSpacing(24)
        perf_grid.setVerticalSpacing(14)

        self.combo_interval = QComboBox()
        self.combo_interval.addItems([str(v) + _["timeout_seconds"] for v in (30, 60, 120, 300, 600)])

        self.combo_threads = QComboBox()
        self.combo_threads.addItems([str(v) for v in range(1, 9)])

        self.combo_retries = QComboBox()
        self.combo_retries.addItems([str(v) for v in range(1, 11)])

        self.chk_auto_start = QCheckBox(_["settings_auto_start"])
        self.chk_auto_start.setObjectName("chk_auto_start")
        self.chk_auto_start.setToolTip(_["settings_auto_start_tip"])

        # Single row of labeled fields (label above, control below)
        fields = [
            (_["settings_interval"], self.combo_interval),
            (_["settings_threads"], self.combo_threads),
            (_["settings_retries"], self.combo_retries),
        ]
        for idx, (title, widget) in enumerate(fields):
            lbl = QLabel(title)
            lbl.setStyleSheet(_HINT_STYLE)
            perf_grid.addWidget(lbl, 0, idx)
            perf_grid.addWidget(widget, 1, idx)

        # Auto-start checkbox on its own row, left-aligned
        perf_grid.addWidget(self.chk_auto_start, 2, 0, 1, 3)
        perf_grid.setColumnStretch(0, 1)
        perf_grid.setColumnStretch(1, 1)
        perf_grid.setColumnStretch(2, 1)

        layout.addWidget(perf_group)

        # Group 4: Schedule
        sched_group = QGroupBox(_["settings_schedule_group"])
        sched_layout = QVBoxLayout(sched_group)

        self.chk_schedule = QCheckBox(_["settings_schedule_enable"])
        sched_layout.addWidget(self.chk_schedule)

        sched_row = QHBoxLayout()
        sched_row.addWidget(QLabel(_["settings_schedule_start"]))
        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm")
        sched_row.addWidget(self.time_start)
        sched_row.addWidget(QLabel(_["settings_schedule_end"]))
        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm")
        sched_row.addWidget(self.time_end)
        sched_row.addStretch()
        sched_layout.addLayout(sched_row)

        lbl_sched_desc = QLabel(_["settings_schedule_desc"])
        lbl_sched_desc.setStyleSheet(_HINT_STYLE_NO_BOLD)
        lbl_sched_desc.setWordWrap(True)
        sched_layout.addWidget(lbl_sched_desc)

        layout.addWidget(sched_group)

        # Group 5: Export / Import
        export_group = QGroupBox(_["settings_export_group"])
        export_layout = QHBoxLayout(export_group)
        btn_export = QPushButton(_["btn_export"])
        btn_export.setObjectName("btn_secondary")
        btn_export.clicked.connect(self.export_config)
        btn_import = QPushButton(_["btn_import"])
        btn_import.setObjectName("btn_secondary")
        btn_import.clicked.connect(self.import_config)
        export_layout.addWidget(btn_export)
        export_layout.addWidget(btn_import)
        btn_check_update = QPushButton(_["btn_check_update"])
        btn_check_update.setObjectName("btn_secondary")
        btn_check_update.clicked.connect(self.check_update)
        self.btn_check_update = btn_check_update
        export_layout.addWidget(btn_check_update)
        export_layout.addStretch()
        layout.addWidget(export_group)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton(_["btn_save"])
        btn_save.clicked.connect(self.save_settings)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Auto-update support
    # ------------------------------------------------------------------
    def _update_app_dir(self) -> str:
        """Returns the directory the app runs from (next to config.json)."""
        return os.path.dirname(os.path.abspath(self.config_manager.config_path))

    def check_update(self):
        """Checks for a newer version in a background thread."""
        if not self.config_manager.update_enabled:
            QMessageBox.information(self, _["update_checking"], _["update_no_source"])
            return
        feed_url = self.config_manager.update_url
        repo = self.config_manager.update_github_repo
        if not feed_url and not repo:
            QMessageBox.information(self, _["update_checking"], _["update_no_source"])
            return

        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(_["update_checking"])

        from zalo_drive_sync.utils.updater import (check_for_update,
                                                   check_github_release,
                                                   get_current_version)

        current = get_current_version()

        def work():
            try:
                info = check_github_release(repo, current) if repo else None
                if info is None and feed_url:
                    info = check_for_update(feed_url, current)
                if info:
                    self.update_found.emit(info)
                else:
                    self.update_failed.emit("up_to_date")
            except Exception as exc:
                self.update_failed.emit(str(exc))

        self._update_worker = self._start_worker(work)

    def _on_update_failed(self, reason: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(_["btn_check_update"])
        if reason == "up_to_date":
            from zalo_drive_sync.utils.updater import get_current_version
            QMessageBox.information(
                self, _["update_up_to_date_title"],
                _["update_up_to_date_msg"].format(get_current_version())
            )
        elif reason == "no_source":
            QMessageBox.information(self, _["update_checking"], _["update_no_source"])
        else:
            QMessageBox.critical(self, _["btn_check_update"], _["update_check_failed"])

    def _on_update_found(self, info: dict):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(_["btn_check_update"])
        version = info.get("version", "?")
        notes = (info.get("notes") or "").strip() or "-"
        reply = QMessageBox.question(
            self, _["update_available_title"],
            _["update_available_msg"].format(version, notes[:400]),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return
        download_url = info.get("download_url")
        if not download_url:
            QMessageBox.critical(self, _["btn_check_update"], _["update_download_failed"])
            return

        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText(_["update_downloading"])
        app_dir = self._update_app_dir()
        zip_path = os.path.join(app_dir, "_updates", f"zalosync_update_{version}.zip")

        from zalo_drive_sync.utils.updater import download_update

        def work():
            ok = download_update(download_url, zip_path)
            if ok:
                self.update_downloaded.emit(zip_path)
            else:
                self.update_failed.emit("download")

        self._update_worker = self._start_worker(work)

    def _on_update_downloaded(self, zip_path: str):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText(_["btn_check_update"])
        app_dir = self._update_app_dir()

        from zalo_drive_sync.utils.updater import apply_update
        ok = apply_update(zip_path, app_dir)
        if not ok:
            QMessageBox.critical(self, _["btn_check_update"], _["update_download_failed"])
            return
        QMessageBox.information(self, _["btn_check_update"], _["update_restarting"])
        if self.quit_requested:
            self.quit_requested.emit()

    def load_settings(self):
        """Populates UI controls from ConfigManager."""
        self.combo_group_name.clear()
        self.combo_group_name.addItems([self.config_manager.group_name] if self.config_manager.group_name else [])
        self.combo_group_name.setCurrentText(self.config_manager.group_name or "")

        self.txt_download_folder.setText(self.config_manager.download_folder)
        self.txt_download_timeout.setText(str(self.config_manager.download_timeout))
        self.txt_gdrive_folder.setText(self.config_manager.gdrive_folder_id)

        ext_list = self.config_manager.extensions
        self.txt_extensions.setText(", ".join(ext_list))

        self._set_combo_keep(self.combo_interval, str(self.config_manager.check_interval) + _["timeout_seconds"])
        self._set_combo_keep(self.combo_threads, str(self.config_manager.thread_number))
        self._set_combo_keep(self.combo_retries, str(self.config_manager.max_retry))
        dup_action = self.config_manager.get("duplicate_action", "rename")
        self._set_dup_action(dup_action)

        self.chk_auto_start.setChecked(self.config_manager.auto_start or is_auto_start_enabled())

        self.chk_schedule.setChecked(self.config_manager.schedule_enabled)
        try:
            s = self.config_manager.schedule_start
            e = self.config_manager.schedule_end
            self.time_start.setTime(QTime(int(s.split(":")[0]), int(s.split(":")[1])))
            self.time_end.setTime(QTime(int(e.split(":")[0]), int(e.split(":")[1])))
        except Exception:
            pass

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if folder:
            self.txt_download_folder.setText(folder)

    def set_group_names(self, names):
        """Populates the group dropdown with names fetched from Zalo."""
        self._group_names = list(names)
        current = self.combo_group_name.currentText().strip()
        self.combo_group_name.clear()
        self.combo_group_name.addItems(self._group_names)
        if current and current not in self._group_names:
            self.combo_group_name.addItem(current)
        self.combo_group_name.setCurrentText(current)

    def _on_groups_loaded(self, names):
        if not names:
            QMessageBox.information(
                self, _["settings_group_load"],
                _["settings_group_empty"]
            )
        else:
            self.set_group_names(names)
        self.btn_login_zalo.setEnabled(True)
        self.btn_login_zalo.setText(_["login_connected"])

    def _on_groups_error(self, message):
        self.btn_login_zalo.setEnabled(True)
        self.btn_login_zalo.setText(_["login_connected"])
        QMessageBox.critical(self, _["settings_group_load"],
                             f"{_['settings_group_error']}\n{message}")

    def _start_worker(self, work) -> QThread:
        """Runs a function in a background QThread that cleans itself up."""
        worker = QThread()
        worker.run = work
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return worker

    def _on_connect_clicked(self):
        """One button: login if not connected, otherwise refresh the group list."""
        if self._login_ok:
            self.load_group_names()
        else:
            self.login_zalo()

    def login_zalo(self):
        """Logs into Zalo (QR or saved session) via the shared controller."""
        if self.zalo_controller is None:
            QMessageBox.information(
                self, _["login_title"], _["login_no_controller"]
            )
            return
        if self._login_worker and self._login_worker.isRunning():
            return

        self.btn_login_zalo.setEnabled(False)
        self.btn_login_zalo.setText(_["login_connecting"])

        controller = self.zalo_controller

        def work():
            try:
                ok = controller.ensure_zalo_running()
            except Exception:
                ok = False
            self.login_done.emit(ok)

        self._login_worker = self._start_worker(work)

    def _on_group_selected(self, index: int):
        """Auto-saves the selected group to config immediately."""
        name = self.combo_group_name.itemText(index).strip()
        if not name:
            return
        if name != self.config_manager.group_name:
            self.config_manager.set("group_name", name)

    def _on_dup_toggled(self, checked: bool):
        """Keeps duplicate-strategy checkboxes mutually exclusive."""
        if not checked:
            return
        sender = self.sender()
        for chk in (self.chk_dup_rename, self.chk_dup_skip, self.chk_dup_overwrite):
            if chk is not sender:
                chk.setChecked(False)

    def _get_dup_action(self) -> str:
        if self.chk_dup_skip.isChecked():
            return "skip"
        if self.chk_dup_overwrite.isChecked():
            return "overwrite"
        return "rename"

    def _set_combo_keep(self, combo, text: str):
        """Selects text in a combo, inserting it as an option if not preset.
        Prevents silently losing old config values that fall outside presets."""
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            return
        combo.addItem(text)
        combo.setCurrentIndex(combo.count() - 1)

    def _combo_int(self, combo) -> int:
        """Extracts the integer value from a numeric combo (e.g. '120 giây')."""
        text = combo.currentText().strip()
        try:
            return int(text)
        except ValueError:
            digits = "".join(c for c in text if c.isdigit())
            return int(digits) if digits else 1

    def _timeout_value(self) -> int:
        """Parses the download-timeout field; defaults to 300 if invalid/empty."""
        text = self.txt_download_timeout.text().strip()
        try:
            val = int(text)
        except ValueError:
            return _DEFAULT_TIMEOUT
        return max(_TIMEOUT_MIN, min(val, _TIMEOUT_MAX))

    def _set_dup_action(self, action: str):
        self.chk_dup_rename.setChecked(True)
        if action == "skip":
            self.chk_dup_skip.setChecked(True)
        elif action == "overwrite":
            self.chk_dup_overwrite.setChecked(True)

    def _on_login_done(self, ok: bool):
        self.set_login_state(ok)
        if ok:
            self.load_group_names()

    def set_login_state(self, ok: bool):
        """Updates the login button text from any source (header/settings)."""
        self._login_ok = bool(ok)
        if not hasattr(self, "btn_login_zalo"):
            return
        self.btn_login_zalo.setEnabled(True)
        self.btn_login_zalo.setText(_["login_connected"] if ok else _["btn_login_zalo"])

    def load_group_names(self):
        """Fetches the live Zalo group list via the shared controller."""
        controller = self.zalo_controller
        if controller is None:
            QMessageBox.information(
                self, _["settings_group_load"],
                _["settings_group_empty"]
            )
            return

        self.btn_login_zalo.setEnabled(False)
        self.btn_login_zalo.setText(_["settings_group_loading"])

        def work():
            try:
                if not controller.ensure_zalo_running():
                    self.groups_error.emit(_["settings_group_not_logged"])
                    return
                names = [name for name, _ in controller.list_groups()]
                self.groups_loaded.emit(names)
            except Exception as e:
                self.groups_error.emit(str(e))

        self._group_worker = self._start_worker(work)

    def save_settings(self):
        """Saves values back to config.json and updates system startup."""
        group_name = self.combo_group_name.currentText().strip()

        folder = self.txt_download_folder.text().strip()
        gdrive_id = self.txt_gdrive_folder.text().strip()

        raw_exts = self.txt_extensions.text().split(",")
        exts = [e.strip() if e.strip().startswith(".") else f".{e.strip()}" for e in raw_exts if e.strip()]

        warnings = []
        if not gdrive_id:
            warnings.append(_["settings_missing_gdrive"])
        if not group_name:
            warnings.append(_["settings_missing_group"])
        if not exts:
            warnings.append(_["settings_missing_exts"])

        if folder and not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                warnings.append(_["settings_folder_create"])
            except Exception:
                warnings.append(f"{_['settings_folder']} {folder}")

        if warnings:
            QMessageBox.warning(self, _["save_warning_title"], "\n".join(warnings))

        sched_start = self.time_start.time().toString("HH:mm")
        sched_end = self.time_end.time().toString("HH:mm")

        config_data = {
            "group_name": group_name,
            "download_folder": folder,
            "download_timeout": self._timeout_value(),
            "gdrive_folder_id": gdrive_id,
            "extensions": exts,
            "check_interval": self._combo_int(self.combo_interval),
            "interval": self._combo_int(self.combo_interval),
            "thread_number": self._combo_int(self.combo_threads),
            "max_retry": self._combo_int(self.combo_retries),
            "duplicate_action": self._get_dup_action(),
            "auto_start": self.chk_auto_start.isChecked(),
            "auto_start_windows": self.chk_auto_start.isChecked(),
            "schedule_enabled": self.chk_schedule.isChecked(),
            "schedule_start": sched_start,
            "schedule_end": sched_end
        }

        self.config_manager.update_all(config_data)
        set_auto_start(self.chk_auto_start.isChecked())

        QMessageBox.information(self, _["save_success_title"], _["save_success_msg"])
        if self.settings_saved:
            self.settings_saved.emit()

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, _["btn_export"], "zalosync_backup.zsync", _["export_filter"])
        if not path:
            return
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                cfg = self.config_manager._config
                zf.writestr("config.json", json.dumps(cfg, indent=4, ensure_ascii=False))
            with open(path, 'wb') as f:
                f.write(buf.getvalue())
            QMessageBox.information(self, _["save_success_title"], _["export_success"])
        except Exception as e:
            QMessageBox.critical(self, _["save_success_title"], _["export_failed"].format(e))

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, _["btn_import"], "", _["export_filter"])
        if not path:
            return
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                if "config.json" not in zf.namelist():
                    raise ValueError("Missing config.json")
                data = json.loads(zf.read("config.json"))
            self.config_manager.update_all(data)
            self.load_settings()
            QMessageBox.information(self, _["save_success_title"], _["import_success"])
            if self.settings_saved:
                self.settings_saved.emit()
        except Exception:
            QMessageBox.critical(self, _["save_success_title"], _["import_failed"])
