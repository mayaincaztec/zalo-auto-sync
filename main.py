import os
import sys
import shutil
import threading

if getattr(sys, 'frozen', False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
    _MEI = getattr(sys, '_MEIPASS', None)
    if _MEI:
        for _name in ('config.json', 'node_bridge'):
            _src = os.path.join(_MEI, _name)
            _dst = os.path.join(PROJECT_ROOT, _name)
            if not os.path.exists(_src):
                continue
            try:
                if os.path.isdir(_src):
                    if os.path.isdir(_dst):
                        # re-extract if key file missing
                        _key = os.path.join(_dst, 'zalo_bridge.js' if _name == 'node_bridge' else '.')
                        if os.path.exists(_key):
                            continue
                        shutil.rmtree(_dst)
                    shutil.copytree(_src, _dst)
                else:
                    if os.path.exists(_dst):
                        continue
                    shutil.copy2(_src, _dst)
            except Exception:
                pass  # best effort
else:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

PARENT_DIR = os.path.dirname(PROJECT_ROOT)

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from PySide6.QtCore import Qt, QSharedMemory
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

APP_SINGLE_INSTANCE_KEY = "ZaloPCAutoDownload_SingleInstance"

from zalo_drive_sync.config.config_manager import ConfigManager
from zalo_drive_sync.database.db_manager import DatabaseManager
from zalo_drive_sync.ui.i18n import _TR as _
from zalo_drive_sync.ui.main_window import MainWindow
from zalo_drive_sync.utils.logger import setup_logger
from zalo_drive_sync.utils import resources


def _exception_hook(exc_type, exc_value, exc_tb):
    import traceback
    try:
        crash_log = os.path.join(PROJECT_ROOT, "logs", "crash.log")
        os.makedirs(os.path.dirname(crash_log), exist_ok=True)
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Lỗi không mong muốn",
                             f"Đã xảy ra lỗi:\n{exc_value}\n\nXem chi tiết trong logs/crash.log")
    except Exception:
        pass


def _activate_existing_instance() -> bool:
    """Brings the already-running app window to the foreground (Windows)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, _["window_title"])
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def main():
    """Main execution entry point."""
    sys.excepthook = _exception_hook
    threading.excepthook = _exception_hook

    config_path = os.path.join(PROJECT_ROOT, "config.json")
    config_manager = ConfigManager(config_path)

    db_path = os.path.join(PROJECT_ROOT, "database.db")
    db_manager = DatabaseManager(db_path)

    if PYSIDE_AVAILABLE:
        app = QApplication(sys.argv)
        app.setApplicationName("ZaloPCAutoDownload")
        app.setOrganizationName("ZaloSync")
        app.setQuitOnLastWindowClosed(False)
        _app_icon = QIcon(resources.icon_ico_path())
        app.setWindowIcon(_app_icon)
        app.setDesktopFileName("ZaloPCAutoDownload")

        single_instance = QSharedMemory(APP_SINGLE_INSTANCE_KEY)
        if single_instance.attach():
            # Another instance is already running -> activate it and exit.
            if not _activate_existing_instance():
                QMessageBox.information(
                    None,
                    _["single_instance_title"],
                    _["single_instance_msg"]
                )
            return
        if not single_instance.create(1):
            # A stale segment (left by a crashed instance) or a race with
            # another instance starting at the same time: treat as duplicate.
            if not _activate_existing_instance():
                QMessageBox.information(
                    None,
                    _["single_instance_title"],
                    _["single_instance_msg"]
                )
            return
        app.single_instance = single_instance

        main_window = MainWindow(
            config_manager=config_manager,
            db_manager=db_manager,
        )

        log_dir = os.path.join(PROJECT_ROOT, "logs")
        setup_logger(log_dir=log_dir, ui_callback=main_window.emit_log)

        if "--minimized" not in sys.argv:
            main_window.show()
        else:
            main_window.tray_icon.notify(
                "Zalo PC Sync Started",
                "Application started minimized in system tray."
            )

        sys.exit(app.exec())
    else:
        setup_logger(log_dir=os.path.join(PROJECT_ROOT, "logs"))
        print("\n[Warning] PySide6 GUI library is not installed in this environment.")
        print("To run the desktop GUI app on Windows:")
        print("  1. Ensure Python 3.12 is installed.")
        print("  2. Install requirements: pip install -r requirements.txt")
        print("  3. Launch: python main.py\n")


if __name__ == "__main__":
    main()
