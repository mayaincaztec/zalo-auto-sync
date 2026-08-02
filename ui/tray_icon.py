"""
System Tray Icon Module
PySide6 QSystemTrayIcon integration with context menu and tray notifications.
"""

from typing import Callable, Optional

try:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

from zalo_drive_sync.ui.i18n import _TR as _


class AppTrayIcon(QSystemTrayIcon if PYSIDE_AVAILABLE else object):
    """System Tray Icon for running app in background."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_toggle_sync: Optional[Callable[[], None]] = None,
        on_open_app: Optional[Callable[[], None]] = None,
        on_exit_app: Optional[Callable[[], None]] = None
    ):
        if not PYSIDE_AVAILABLE:
            return
        super().__init__(parent)

        self.on_toggle_sync = on_toggle_sync
        self.on_open_app = on_open_app
        self.on_exit_app = on_exit_app

        try:
            from PySide6.QtGui import QIcon
            from zalo_drive_sync.utils.resources import icon_ico_path
            self.setIcon(QIcon(icon_ico_path()))
        except Exception:
            pass
        self.setToolTip(_["tray_tooltip"])
        self.init_menu()

    def init_menu(self):
        menu = QMenu()

        self.action_toggle_sync = QAction(_["tray_start_sync"], self)
        if self.on_toggle_sync:
            self.action_toggle_sync.triggered.connect(self.on_toggle_sync)
        menu.addAction(self.action_toggle_sync)

        menu.addSeparator()

        action_open = QAction(_["tray_open"], self)
        if self.on_open_app:
            action_open.triggered.connect(self.on_open_app)
        menu.addAction(action_open)

        action_exit = QAction(_["tray_exit"], self)
        if self.on_exit_app:
            action_exit.triggered.connect(self.on_exit_app)
        menu.addAction(action_exit)

        self.setContextMenu(menu)
        self.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger and self.on_open_app:
            self.on_open_app()

    def notify(self, title: str, message: str, is_error: bool = False):
        """Shows Windows desktop balloon notification."""
        if PYSIDE_AVAILABLE and self.isSystemTrayAvailable():
            icon_type = QSystemTrayIcon.Critical if is_error else QSystemTrayIcon.Information
            self.showMessage(title, message, icon_type, 3000)

    def update_sync_state(self, is_running: bool):
        if self.action_toggle_sync:
            self.action_toggle_sync.setText(_["tray_stop_sync"] if is_running else _["tray_start_sync"])
