"""
Resource Path Resolution
Returns paths to bundled assets (icons) in both dev and frozen (PyInstaller) mode.
"""

import os
import sys


def _base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_icon(filename: str = "app_icon.ico") -> str:
    """Return absolute path to an icon file, checking frozen MEIPASS first."""
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, "icons", filename))
    candidates.append(os.path.join(_base_dir(), "icons", filename))
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[-1]


def icon_png_path() -> str:
    return resolve_icon("app_icon.png")


def icon_ico_path() -> str:
    return resolve_icon("app_icon.ico")
