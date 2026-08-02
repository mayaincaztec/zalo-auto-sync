"""
Unit Tests for ConfigManager
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from zalo_drive_sync.config.config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):

    def setUp(self):
        ConfigManager._instance = None
        self.test_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.test_dir, "test_config.json")

    def tearDown(self):
        ConfigManager._instance = None
        for root, _, files in os.walk(self.test_dir, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass
            os.rmdir(root)

    def test_default_config_creation(self):
        cfg = ConfigManager(self.config_file)
        self.assertTrue(os.path.exists(self.config_file))
        self.assertEqual(cfg.check_interval, 5)
        self.assertEqual(cfg.max_retry, 3)
        self.assertEqual(cfg.group_name, "Team Alpha Workgroup")

    def test_config_set_and_get(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("gdrive_folder_id", "test_folder_123")
        cfg.set("group_name", "Kế Toán Company")
        self.assertEqual(cfg.gdrive_folder_id, "test_folder_123")
        self.assertEqual(cfg.group_name, "Kế Toán Company")

        # Reload from disk
        cfg2 = ConfigManager(self.config_file)
        cfg2.load()
        self.assertEqual(cfg2.gdrive_folder_id, "test_folder_123")
        self.assertEqual(cfg2.group_name, "Kế Toán Company")

    def test_singleton_returns_same_instance(self):
        cfg1 = ConfigManager(self.config_file)
        cfg2 = ConfigManager(self.config_file)
        self.assertIs(cfg1, cfg2)

    def test_singleton_initialized_once(self):
        ConfigManager._instance = None
        cfg1 = ConfigManager(self.config_file)
        cfg1.set("gdrive_folder_id", "abc")
        cfg2 = ConfigManager(self.config_file)
        cfg2.set("gdrive_folder_id", "xyz")
        self.assertEqual(cfg1.gdrive_folder_id, "xyz")  # same object

    def test_group_names_single(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("group_name", "Nhóm A")
        self.assertEqual(cfg.group_names, ["Nhóm A"])

    def test_group_names_empty(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("group_name", "")
        self.assertEqual(cfg.group_names, [])

    def test_properties_fall_back_to_defaults(self):
        cfg = ConfigManager(self.config_file)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump({}, f)
        cfg.load()
        self.assertEqual(cfg.download_folder, os.path.expanduser("~/Documents/Zalo Received Files"))
        self.assertEqual(cfg.download_timeout, 300)
        self.assertEqual(cfg.theme, "dark")
        self.assertEqual(cfg.auto_start, False)
        self.assertFalse(cfg.schedule_enabled)
        self.assertEqual(cfg.schedule_start, "22:00")
        self.assertEqual(cfg.schedule_end, "06:00")
        self.assertEqual(cfg.thread_number, 2)
        self.assertEqual(cfg.interval, 5)  # alias for check_interval
        self.assertEqual(cfg.extensions, [".pdf", ".docx", ".xlsx", ".png", ".jpg", ".zip", ".rar", ".mp4", ".txt"])
        self.assertEqual(cfg.gdrive_folder_id, "")
        self.assertEqual(cfg.group_name, "Team Alpha Workgroup")
        self.assertEqual(cfg.max_retry, 3)

    def test_int_coercion_for_numeric_properties(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("download_timeout", "45")
        cfg.set("check_interval", "7")
        cfg.set("max_retry", "2")
        cfg.set("thread_number", "4")
        self.assertEqual(cfg.download_timeout, 45)
        self.assertEqual(cfg.check_interval, 7)
        self.assertEqual(cfg.max_retry, 2)
        self.assertEqual(cfg.thread_number, 4)

    def test_bool_coercion(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("auto_start", 1)
        cfg.set("schedule_enabled", "yes")
        self.assertTrue(cfg.auto_start)
        self.assertTrue(cfg.schedule_enabled)

    def test_get_with_custom_default(self):
        cfg = ConfigManager(self.config_file)
        self.assertEqual(cfg.get("nonexistent_key", "fallback"), "fallback")
        self.assertIsNone(cfg.get("nonexistent_key"))

    def test_update_all_saves_multiple_keys(self):
        cfg = ConfigManager(self.config_file)
        cfg.update_all({"group_name": "G", "max_retry": 5, "theme": "light"})
        self.assertEqual(cfg.group_name, "G")
        self.assertEqual(cfg.max_retry, 5)
        self.assertEqual(cfg.theme, "light")
        cfg2 = ConfigManager(self.config_file)
        self.assertEqual(cfg2.get("max_retry"), 5)

    def test_load_corrupt_json_resets_to_defaults(self):
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json !!!")
        cfg = ConfigManager(self.config_file)
        cfg.load()
        self.assertEqual(cfg.check_interval, 5)
        self.assertEqual(cfg.group_name, "Team Alpha Workgroup")

    def test_save_returns_false_on_failure(self):
        cfg = ConfigManager(self.config_file)
        with patch("zalo_drive_sync.config.config_manager.os.makedirs", side_effect=OSError("denied")):
            self.assertFalse(cfg.save())

    def test_created_file_is_valid_utf8(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("group_name", "Tiếng Việt ẮẶỆ")
        raw = open(self.config_file, "r", encoding="utf-8").read()
        self.assertIn("Tiếng Việt ẮẶỆ", raw)

    def test_update_properties_defaults(self):
        cfg = ConfigManager(self.config_file)
        self.assertTrue(cfg.update_enabled)
        self.assertEqual(cfg.update_url, "")
        self.assertEqual(cfg.update_github_repo, "loisude/Zalo-PC-Auto-Sync")

    def test_update_properties_set(self):
        cfg = ConfigManager(self.config_file)
        cfg.update_all({
            "update_enabled": False,
            "update_url": "https://example.com/feed.json",
            "update_github_repo": "owner/repo",
        })
        self.assertFalse(cfg.update_enabled)
        self.assertEqual(cfg.update_url, "https://example.com/feed.json")
        self.assertEqual(cfg.update_github_repo, "owner/repo")

    def test_update_url_strips_whitespace(self):
        cfg = ConfigManager(self.config_file)
        cfg.set("update_url", "  https://example.com/x  ")
        self.assertEqual(cfg.update_url, "https://example.com/x")


if __name__ == "__main__":
    unittest.main()
