"""
Logger Utility Module
Sets up Loguru logger with daily rotating files and custom PySide6 Qt Signal redirection.
"""

import os
import sys
from typing import Callable, Optional

try:
    from loguru import logger
    LOGURU_AVAILABLE = True
except ImportError:
    LOGURU_AVAILABLE = False


class LogSignalSink:
    """Custom Loguru sink redirecting log entries to a callback or PySide6 Signal."""

    def __init__(self, callback: Callable[[str, str], None]):
        self.callback = callback

    def write(self, message):
        try:
            record = message.record
            level = record["level"].name
            text = record["message"]
            self.callback(level, text)
        except Exception:
            pass


def setup_logger(log_dir: str = "logs", ui_callback: Optional[Callable[[str, str], None]] = None):
    """Configures Loguru logger sinks for console, daily file rotation, and optional UI widget.
    
    Args:
        log_dir: Directory to save log files.
        ui_callback: Callback receiving (level_name, formatted_message) for GUI display.
    """
    if not LOGURU_AVAILABLE:
        print("[Warning] Loguru package not installed. Using standard stdout logging.")
        return

    os.makedirs(log_dir, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console stdout handler (if available, e.g. not frozen GUI mode)
    if sys.stdout is not None:
        logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="INFO"
        )

    # Daily rotating log file handler
    file_path = os.path.join(log_dir, "zalo_sync_{time:YYYY-MM-DD}.log")
    logger.add(
        file_path,
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}"
    )

    # UI widget sink handler
    if ui_callback:
        sink = LogSignalSink(ui_callback)
        logger.add(
            sink.write,
            level="DEBUG",
            format="{message}"
        )

    logger.info("Loguru logger initialized successfully.")
