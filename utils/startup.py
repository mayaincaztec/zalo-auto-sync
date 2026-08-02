"""
Windows Startup Utility
Manages HKCU Registry entry to enable or disable automatic app start on Windows boot.
"""

import os
import sys

# winreg is only available on Windows platforms
try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    WINREG_AVAILABLE = False


REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "ZaloPCSyncDrive"


def set_auto_start(enable: bool = True, exe_path: str = None) -> bool:
    """Enables or disables auto-start with Windows login via HKCU registry key.
    
    Args:
        enable: True to enable auto-start, False to remove.
        exe_path: Path to executable. Defaults to sys.executable.
        
    Returns:
        True if registry update succeeded, False otherwise.
    """
    if not WINREG_AVAILABLE:
        return False

    if exe_path is None:
        exe_path = os.path.abspath(sys.executable)

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def is_auto_start_enabled() -> bool:
    """Checks if auto-start registry key exists."""
    if not WINREG_AVAILABLE:
        return False

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
        try:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return bool(val)
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False
