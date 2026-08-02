"""
Zalo Service Helper
Detects default Zalo PC download locations on Windows, handles file stability checks.
"""

import os
import time
from typing import Optional


def get_default_zalo_folder() -> str:
    """Detects default Zalo Received Files directory on Windows/OS."""
    user_home = os.path.expanduser("~")
    possible_paths = [
        os.path.join(user_home, "Documents", "Zalo Received Files"),
        os.path.join(user_home, "Downloads", "Zalo Received Files"),
        os.path.join(user_home, "Downloads")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    default_dir = os.path.join(user_home, "Documents", "Zalo Received Files")
    os.makedirs(default_dir, exist_ok=True)
    return default_dir


def wait_for_file_stability(filepath: str, check_interval: float = 1.0, timeout: float = 30.0) -> bool:
    """Ensures file is fully written and no longer locked by Zalo PC download process.
    
    Args:
        filepath: Path to the downloaded file.
        check_interval: Delay between size checks in seconds.
        timeout: Maximum duration to wait for stability.
        
    Returns:
        True if file size stabilized and file can be opened for reading, False otherwise.
    """
    if not os.path.exists(filepath):
        return False

    start_time = time.time()
    last_size = -1

    while time.time() - start_time < timeout:
        try:
            current_size = os.path.getsize(filepath)
            # Check if size stopped growing and > 0 bytes
            if current_size == last_size and current_size > 0:
                # Test opening file with read lock
                with open(filepath, 'rb') as f:
                    f.read(1)
                return True
            last_size = current_size
        except (PermissionError, OSError):
            pass
        time.sleep(check_interval)

    return False
