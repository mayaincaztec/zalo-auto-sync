"""
Config Manager Module
Manages application settings stored in config.json with thread-safe access.
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "group_name": "Team Alpha Workgroup",
    "group_names": [],
    "check_interval": 3600,
    "auto_schedule_mode": "interval",
    "auto_interval_hours": 1,
    "daily_times": ["08:00"],
    "download_folder": os.path.expanduser("~/Documents/Zalo Received Files"),
    "download_timeout": 300,
    "extensions": [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".zip", ".rar", ".mp4", ".txt"],
    "max_retry": 3,
    "thread_number": 2,
    "duplicate_action": "rename",
    "auto_start": False,
    "theme": "dark",
    "schedule_enabled": False,
    "schedule_start": "22:00",
    "schedule_end": "06:00",
    "speed_limit": 0,
    "update_enabled": False,
    "update_url": "",
    "update_github_repo": "mayaincaztec/zalo-auto-sync"
}


class ConfigManager:
    """Thread-safe configuration manager singleton."""

    _instance: Optional['ConfigManager'] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: str = "config.json") -> 'ConfigManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ConfigManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config_path: str = "config.json") -> None:
        if self._initialized:
            return
        self.config_path = config_path
        self._rw_lock = threading.RLock()
        self._config: Dict[str, Any] = {}
        self.load()
        self._initialized = True

    def load(self) -> Dict[str, Any]:
        """Loads configuration from JSON file or creates default if missing."""
        with self._rw_lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        self._config = {**DEFAULT_CONFIG, **loaded}
                except Exception:
                    self._config = DEFAULT_CONFIG.copy()
                    self.save()
            else:
                self._config = DEFAULT_CONFIG.copy()
                self.save()
            return self._config

    def save(self) -> bool:
        """Saves current configuration to JSON file."""
        with self._rw_lock:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.config_path)), exist_ok=True)
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, indent=4, ensure_ascii=False)
                return True
            except Exception:
                return False

    def get(self, key: str, default: Any = None) -> Any:
        """Gets a configuration value."""
        with self._rw_lock:
            return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Sets a configuration value and saves automatically."""
        with self._rw_lock:
            self._config[key] = value
            self.save()

    def update_all(self, new_config: Dict[str, Any]) -> None:
        """Updates multiple configuration keys and saves."""
        with self._rw_lock:
            self._config.update(new_config)
            self.save()

    @property
    def group_name(self) -> str:
        """Compatibility alias for callers that still expect one group."""
        names = self.group_names
        if names:
            return names[0]
        return str(self.get("group_name", DEFAULT_CONFIG["group_name"])).strip()

    @property
    def group_names(self) -> List[str]:
        """Returns the selected Zalo groups, migrating the legacy single value."""
        raw_names = self.get("group_names", [])
        result: List[str] = []
        if isinstance(raw_names, list):
            for value in raw_names:
                name = str(value).strip()
                if name and name not in result:
                    result.append(name)
        if result:
            return result
        legacy_name = str(self.get("group_name", DEFAULT_CONFIG["group_name"])).strip()
        return [legacy_name] if legacy_name else []

    @property
    def auto_schedule_mode(self) -> str:
        mode = str(self.get("auto_schedule_mode", "interval")).strip().lower()
        return mode if mode in {"interval", "daily"} else "interval"

    @property
    def auto_interval_hours(self) -> int:
        try:
            value = int(self.get("auto_interval_hours", 1))
        except (TypeError, ValueError):
            value = 1
        return value if value in {1, 3, 6, 12} else 1

    @property
    def daily_times(self) -> List[str]:
        raw_times = self.get("daily_times", ["08:00"])
        if not isinstance(raw_times, list):
            raw_times = []
        result: List[str] = []
        for value in raw_times:
            text = str(value).strip()
            try:
                hour, minute = map(int, text.split(":"))
            except (TypeError, ValueError):
                continue
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                normalized = f"{hour:02d}:{minute:02d}"
                if normalized not in result:
                    result.append(normalized)
        return sorted(result)[:3] or ["08:00"]

    @property
    def schedule_enabled(self) -> bool:
        return bool(self.get("schedule_enabled", False))

    @property
    def schedule_start(self) -> str:
        return str(self.get("schedule_start", "22:00"))

    @property
    def schedule_end(self) -> str:
        return str(self.get("schedule_end", "06:00"))

    @property
    def download_folder(self) -> str:
        return self.get("download_folder", DEFAULT_CONFIG["download_folder"])

    @property
    def download_timeout(self) -> int:
        return int(self.get("download_timeout", 300))

    @property
    def extensions(self) -> List[str]:
        return self.get("extensions", DEFAULT_CONFIG["extensions"])

    @property
    def check_interval(self) -> int:
        if self.auto_schedule_mode == "interval":
            return self.auto_interval_hours * 3600
        try:
            return max(1, int(self.get("check_interval", 3600)))
        except (TypeError, ValueError):
            return 3600

    @property
    def interval(self) -> int:
        return self.check_interval

    @property
    def max_retry(self) -> int:
        return int(self.get("max_retry", 3))

    @property
    def thread_number(self) -> int:
        return int(self.get("thread_number", 2))

    @property
    def auto_start(self) -> bool:
        return bool(self.get("auto_start", False))

    @property
    def theme(self) -> str:
        return self.get("theme", "dark")

    @property
    def update_enabled(self) -> bool:
        return bool(self.get("update_enabled", False))

    @property
    def update_url(self) -> str:
        return str(self.get("update_url", "")).strip()

    @property
    def update_github_repo(self) -> str:
        return str(self.get("update_github_repo", "")).strip()
