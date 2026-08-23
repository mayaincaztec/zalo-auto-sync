"""
PySide6 QSS Stylesheets
Provides modern Dark Mode and Light Mode styles for Qt widgets.
"""

DARK_THEME = """
QMainWindow {
    background-color: #121824;
    color: #E2E8F0;
}

QWidget {
    font-family: 'Segoe UI', -apple-system, Roboto, sans-serif;
    font-size: 13px;
    color: #E2E8F0;
}

QGroupBox {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #94A3B8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #38BDF8;
}

QLineEdit, QSpinBox, QComboBox, QTimeEdit, QListWidget {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 12px;
    color: #F8FAFC;
    selection-background-color: #0284C7;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QListWidget:focus {
    border: 1px solid #38BDF8;
}

QComboBox QAbstractItemView {
    background-color: #0F172A;
    color: #F8FAFC;
    selection-background-color: #0284C7;
    selection-color: #FFFFFF;
    border: 1px solid #334155;
    outline: none;
}

QComboBox QAbstractItemView::item {
    padding: 6px 12px;
    min-height: 24px;
}

QComboBox QAbstractItemView::item:hover {
    background-color: #1E293B;
}

QListWidget::item {
    padding: 5px 8px;
    border-radius: 4px;
}

QListWidget::item:hover {
    background-color: #1E293B;
}

QListWidget::item:selected {
    background-color: #0C4A6E;
    color: #FFFFFF;
}

QPushButton {
    background-color: #0284C7;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #0369A1;
}

QPushButton:pressed {
    background-color: #075985;
}

QPushButton#btn_stop {
    background-color: #EF4444;
}

QPushButton#btn_stop:hover {
    background-color: #DC2626;
}

QFrame#header_bar {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1E293B, stop:1 #1B2A44);
    border: 1px solid #334155;
    border-radius: 12px;
}

QLabel#brand_title {
    font-size: 17px;
    font-weight: 700;
    color: #F8FAFC;
}

QLabel#brand_subtitle {
    font-size: 11px;
    color: #7C8DB5;
}

QLabel#sync_status {
    padding: 5px 14px;
    border-radius: 13px;
    background-color: rgba(239, 68, 68, 0.14);
    color: #F87171;
    font-weight: 700;
    font-size: 12px;
}

QLabel#sync_status[state="active"] {
    background-color: rgba(16, 185, 129, 0.14);
    color: #34D399;
}

QFrame#stat_card {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #1E293B, stop:1 #1B2A44);
    border: 1px solid #334155;
    border-radius: 10px;
}

QLabel#stat_card_title {
    color: #7C8DB5;
    font-size: 11px;
    font-weight: 600;
}

QLabel#stat_card_value {
    font-size: 19px;
    font-weight: 700;
    color: #F8FAFC;
}

QPushButton#btn_secondary {
    background-color: #334155;
    color: #F1F5F9;
}

QPushButton#btn_secondary:hover {
    background-color: #475569;
}

QFrame#btn_menu {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 10px;
}

QPushButton[menuBtn="true"] {
    background: transparent;
    border: none;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 13px;
    border-radius: 7px;
    min-height: 18px;
}

QPushButton[menuBtn="true"]:hover {
    background-color: #1E293B;
}

QPushButton[menuBtn="true"]:pressed {
    background-color: #0B1120;
}

QPushButton#btn_menu_login {
    color: #7DD3FC;
    border-top-left-radius: 9px;
    border-bottom-left-radius: 9px;
}

QPushButton#btn_menu_login[connected="true"] {
    color: #34D399;
}

QPushButton#btn_menu_login[connected="true"]:hover {
    background-color: rgba(16, 185, 129, 0.12);
}

QPushButton#btn_menu_sync {
    color: #F8FAFC;
    background-color: #0284C7;
    margin: 3px 1px;
    border-radius: 7px;
}

QPushButton#btn_menu_sync:hover {
    background-color: #0EA5E9;
}

QPushButton#btn_menu_sync:pressed {
    background-color: #0369A1;
}

QPushButton#btn_menu_sync:disabled {
    background-color: #1E293B;
    color: #64748B;
}

QPushButton#btn_menu_stop {
    color: #F87171;
    border-top-right-radius: 9px;
    border-bottom-right-radius: 9px;
}

QPushButton#btn_menu_stop[active="true"] {
    color: #FFFFFF;
    background-color: #EF4444;
}

QPushButton#btn_menu_stop[active="true"]:hover {
    background-color: #DC2626;
}

QPushButton#btn_menu_stop[active="true"]:pressed {
    background-color: #B91C1C;
}

QTableWidget {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 8px;
    gridline-color: #1E293B;
    alternate-background-color: #1E293B;
}

/* Darken the empty header strip below the row-number column and the corner
   button at the top-left (both default to white on Windows). */
QHeaderView {
    background-color: #0F172A;
}

QTableCornerButton::section {
    background-color: #1E293B;
    border: none;
}

QHeaderView::section {
    background-color: #1E293B;
    color: #94A3B8;
    padding: 8px;
    border: none;
    font-weight: bold;
}

QProgressBar {
    border: none;
    background-color: #1E293B;
    border-radius: 4px;
    text-align: center;
    color: white;
}

QProgressBar::chunk {
    background-color: #10B981;
    border-radius: 4px;
}

QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 8px;
    background-color: #1E293B;
}

QTabBar::tab {
    background-color: #0F172A;
    color: #94A3B8;
    padding: 10px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #1E293B;
    color: #38BDF8;
    font-weight: bold;
}

QPlainTextEdit {
    background-color: #090D16;
    color: #CBD5E1;
    border: 1px solid #334155;
    border-radius: 6px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
}

QMenu {
    background-color: #1E293B;
    color: #E2E8F0;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 8px 24px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #0284C7;
    color: #FFFFFF;
}

QMenu::separator {
    height: 1px;
    background: #334155;
    margin: 4px 8px;
}

QMessageBox, QMessageBox QLabel {
    background-color: #1E293B;
    color: #E2E8F0;
}

QMessageBox QPushButton {
    min-width: 80px;
}
"""



def get_stylesheet(theme: str = "dark") -> str:
    return DARK_THEME
