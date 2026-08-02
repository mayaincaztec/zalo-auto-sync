import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from zalo_drive_sync.services.zalo_controller import (
    QR_FILE,
    GroupFile,
    ZaloController,
)





class TestZaloController(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.test_dir):
            for f in os.listdir(self.test_dir):
                fp = os.path.join(self.test_dir, f)
                try:
                    os.remove(fp)
                except OSError:
                    pass
            try:
                os.rmdir(self.test_dir)
            except OSError:
                pass

    def test_group_file_creation(self):
        gf = GroupFile(
            file_id="test_001",
            message_id="msg_001",
            filename="report.pdf",
            filesize=2048,
            group_name="Alpha",
            sender="User A",
            created_time="2025-01-01 12:00:00"
        )
        self.assertEqual(gf.file_id, "test_001")
        self.assertEqual(gf.filename, "report.pdf")
        self.assertEqual(gf.filesize, 2048)
        self.assertEqual(gf.group_name, "Alpha")

    def test_group_file_to_dict(self):
        gf = GroupFile("id1", "mid1", "doc.txt", 100, "Group1")
        d = gf.to_dict()
        self.assertEqual(d["file_id"], "id1")
        self.assertEqual(d["filename"], "doc.txt")
        self.assertEqual(d["group_name"], "Group1")

    def test_group_file_generates_ids(self):
        gf = GroupFile(file_id="", message_id="", filename="f", filesize=0, group_name="G")
        self.assertTrue(len(gf.file_id) > 0)
        self.assertTrue(len(gf.message_id) > 0)

    def test_has_saved_session_no_cookie(self):
        ctrl = ZaloController()
        with patch("zalo_drive_sync.services.zalo_controller.COOKIE_FILE",
                   os.path.join(self.test_dir, "cookie.json")):
            self.assertFalse(ctrl.has_saved_session())
        # A real saved cookie should report True
        cookie_path = os.path.join(self.test_dir, "cookie.json")
        with open(cookie_path, "w", encoding="utf-8") as f:
            f.write("{}")
        with patch("zalo_drive_sync.services.zalo_controller.COOKIE_FILE", cookie_path):
            self.assertTrue(ctrl.has_saved_session())

    @patch("zalo_drive_sync.services.zalo_controller.subprocess.Popen")
    def test_bridge_startup_fails_without_node(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError("Node not found")
        ctrl = ZaloController()
        result = ctrl.ensure_zalo_running()
        self.assertFalse(result)
        self.assertFalse(ctrl.is_connected)

    @patch("zalo_drive_sync.services.zalo_controller.ZaloController.ensure_zalo_running", return_value=False)
    def test_empty_scan_when_not_logged_in(self, mock_ensure):
        ctrl = ZaloController()
        files = ctrl.scan_group_files("AnyGroup")
        self.assertEqual(len(files), 0)

    @patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command", return_value=None)
    def test_scan_with_active_group_but_no_bridge(self, mock_send):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "TestGroup"
        ctrl._active_group_id = "gid123"
        files = ctrl.scan_group_files("TestGroup")
        self.assertEqual(len(files), 0)

    @patch("zalo_drive_sync.services.zalo_controller.ZaloController._poll_group_messages", return_value=None)
    def test_scan_passes_group_id_to_request_old_messages(self, mock_poll):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "TestGroup"
        ctrl._active_group_id = "gid123"
        calls = []
        with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                   side_effect=lambda cmd, data=None, timeout=30: calls.append((cmd, data, timeout)) or None):
            ctrl.scan_group_files("TestGroup")
        req = [c for c in calls if c[0] == "request_old_messages"]
        self.assertEqual(len(req), 1)
        cmd, data, timeout = req[0]
        self.assertEqual(data, {"groupId": "gid123", "count": 300, "lastMsgId": None})
        self.assertGreaterEqual(timeout, 15)

    def test_scan_passes_last_msg_id_cursor_when_known(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "TestGroup"
        ctrl._active_group_id = "gid123"
        ctrl._last_seen_msg_id["gid123"] = "7777"
        calls = []
        with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                   side_effect=lambda cmd, data=None, timeout=30: calls.append((cmd, data, timeout)) or None):
            with patch("zalo_drive_sync.services.zalo_controller.ZaloController._poll_group_messages",
                       return_value=None):
                ctrl.scan_group_files("TestGroup")
        req = [c for c in calls if c[0] == "request_old_messages"]
        self.assertEqual(req[0][1]["lastMsgId"], "7777")

    def test_restores_cursor_from_config_manager(self):
        config_mock = MagicMock()
        config_mock.get.return_value = {"gid123": "9999"}
        ctrl = ZaloController(config_manager=config_mock)
        self.assertEqual(ctrl._last_seen_msg_id.get("gid123"), "9999")

    def test_persist_cursors_writes_to_config(self):
        config_mock = MagicMock()
        config_mock.get.return_value = {}
        ctrl = ZaloController(config_manager=config_mock)
        ctrl._last_seen_msg_id["gid123"] = "5555"
        ctrl._persist_cursors()
        config_mock.set.assert_called_once()
        args = config_mock.set.call_args[0]
        self.assertEqual(args[0], "last_seen_msg_ids")
        self.assertEqual(args[1], {"gid123": "5555"})

    def test_scan_tracks_last_seen_msg_id_and_passes_delta_cursor(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "TestGroup"
        ctrl._active_group_id = "gid123"
        msg_resp = {
            "status": "ok",
            "data": {
                "groupId": "gid123",
                "total": 2,
                "new_count": 2,
                "messages": [
                    {"msgId": "1000", "msgType": "share.file",
                     "content": {"href": "http://x/a.pdf", "title": "a.pdf"}},
                    {"msgId": "2000", "msgType": "share.file",
                     "content": {"href": "http://x/b.pdf", "title": "b.pdf"}},
                ]
            }
        }

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_group_messages":
                return msg_resp
            return None

        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                       side_effect=fake_send) as mock_send:
                files = ctrl.scan_group_files("TestGroup")
                self.assertEqual(len(files), 2)
                self.assertEqual(ctrl._last_seen_msg_id["gid123"], "2000")

                mock_send.reset_mock()
                mock_send.side_effect = fake_send
                ctrl.scan_group_files("TestGroup")
                poll_calls = [c for c in mock_send.call_args_list if c.args[0] == "get_group_messages"]
                self.assertEqual(poll_calls[0].args[1]["since_msg_id"], "2000")

    def test_poll_fast_exit_when_cache_unchanged(self):
        ctrl = ZaloController()
        ctrl._active_group_id = "gid123"
        ctrl._last_cached_total["gid123"] = 13
        resp = {"status": "ok", "data": {"groupId": "gid123", "total": 13, "new_count": 0, "messages": []}}
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                       return_value=resp) as mock_send:
                result = ctrl._poll_group_messages("G", since_msg_id="5000")
        self.assertIsNotNone(result)
        poll_calls = [c for c in mock_send.call_args_list if c.args[0] == "get_group_messages"]
        self.assertEqual(len(poll_calls), 1)
        self.assertEqual(poll_calls[0].args[1]["since_msg_id"], "5000")

    def test_poll_stable_after_two_identical_reads(self):
        ctrl = ZaloController()
        ctrl._active_group_id = "gid123"
        resp = {"status": "ok", "data": {"groupId": "gid123", "total": 5, "new_count": 5, "messages": []}}
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                       return_value=resp) as mock_send:
                result = ctrl._poll_group_messages("G")
        self.assertIsNotNone(result)
        self.assertEqual(len(mock_send.call_args_list), 3)

    def test_poll_with_zero_total_keeps_polling(self):
        ctrl = ZaloController()
        ctrl._active_group_id = "gid123"
        empty = {"status": "ok", "data": {"groupId": "gid123", "total": 0, "new_count": 0, "messages": []}}
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch.object(ctrl, "_send_command", return_value=empty) as mock_send:
                result = ctrl._poll_group_messages("G", max_wait=0.01)
        self.assertIsNotNone(result)
        self.assertGreater(len(mock_send.call_args_list), 1)

    def test_scan_skips_messages_without_extractable_content(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        msg_resp = {
            "status": "ok",
            "data": {
                "total": 3,
                "new_count": 3,
                "messages": [
                    {"msgId": "10", "content": None},
                    {"msgId": "20", "content": {"title": "no_url"}},
                    {"msgId": "30", "content": {"href": "http://x/ok.pdf", "title": "ok.pdf"}},
                ]
            }
        }

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_group_messages":
                return msg_resp
            return None

        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch.object(ctrl, "_send_command", side_effect=fake_send):
                files = ctrl.scan_group_files("G")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "ok.pdf")

    def test_scan_extends_title_with_extension_by_msg_type(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        msg_resp = {
            "status": "ok",
            "data": {
                "total": 1,
                "new_count": 1,
                "messages": [
                    {"msgId": "42", "msgType": "chat.photo",
                     "content": {"href": "http://x/photo", "title": "photo"}},
                ]
            }
        }

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_group_messages":
                return msg_resp
            return None

        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch.object(ctrl, "_send_command", side_effect=fake_send):
                files = ctrl.scan_group_files("G")
        self.assertEqual(files[0].filename, "photo.jpg")

    def test_scan_handles_non_numeric_msg_id(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        msg_resp = {
            "status": "ok",
            "data": {
                "total": 1,
                "new_count": 1,
                "messages": [
                    {"msgId": "abc-123", "content": {"href": "http://x/f.pdf", "title": "f.pdf"}},
                ]
            }
        }

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_group_messages":
                return msg_resp
            return None

        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch.object(ctrl, "_send_command", side_effect=fake_send):
                files = ctrl.scan_group_files("G")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].message_id, "abc-123")

    def test_scan_out_of_order_msg_ids_keep_max(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        msg_resp = {
            "status": "ok",
            "data": {
                "total": 3,
                "new_count": 3,
                "messages": [
                    {"msgId": "3000", "content": {"href": "http://x/c.pdf", "title": "c.pdf"}},
                    {"msgId": "1000", "content": {"href": "http://x/a.pdf", "title": "a.pdf"}},
                    {"msgId": "2000", "content": {"href": "http://x/b.pdf", "title": "b.pdf"}},
                ]
            }
        }

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_group_messages":
                return msg_resp
            return None

        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            with patch.object(ctrl, "_send_command", side_effect=fake_send):
                ctrl.scan_group_files("G")
        self.assertEqual(ctrl._last_seen_msg_id["gid"], "3000")

    def test_scan_trims_url_map_over_limit(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        with patch("zalo_drive_sync.services.zalo_controller._MAX_URL_MAP", 3):
            msg_resp = {
                "status": "ok",
                "data": {
                    "total": 5,
                    "new_count": 5,
                    "messages": [
                        {"msgId": str(i), "content": {"href": f"http://x/{i}.pdf", "title": f"{i}.pdf"}}
                        for i in range(5)
                    ]
                }
            }

            def fake_send(cmd, data=None, timeout=30):
                if cmd == "get_group_messages":
                    return msg_resp
                return None

            with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
                with patch.object(ctrl, "_send_command", side_effect=fake_send):
                    ctrl.scan_group_files("G")
        self.assertLessEqual(len(ctrl._message_url_map), 3)

    def test_scan_opens_group_when_active_group_differs(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl.active_group = "Other"
        ctrl._active_group_id = "gid"
        with patch.object(ctrl, "open_group", return_value=True) as mock_open:
            with patch.object(ctrl, "_poll_group_messages", return_value=None):
                ctrl.scan_group_files("G")
        mock_open.assert_called_once_with("G")

    def test_extract_file_info_photo(self):
        content = {
            "href": "https://f56-zpg-r.zdn.vn/photo.jpg",
            "title": "my_photo.jpg",
            "description": ""
        }
        info = ZaloController._extract_file_info(content)
        self.assertIsNotNone(info)
        href, title, fsize = info
        self.assertEqual(href, "https://f56-zpg-r.zdn.vn/photo.jpg")
        self.assertEqual(title, "my_photo.jpg")

    def test_extract_file_info_file(self):
        content = {
            "href": "https://f56-zpg-r.zdn.vn/document.pdf",
            "title": "report.pdf"
        }
        info = ZaloController._extract_file_info(content)
        self.assertIsNotNone(info)
        self.assertEqual(info[0], "https://f56-zpg-r.zdn.vn/document.pdf")
        self.assertEqual(info[1], "report.pdf")

    def test_extract_file_info_missing(self):
        self.assertIsNone(ZaloController._extract_file_info("plain string"))
        self.assertIsNone(ZaloController._extract_file_info({"no_href": True}))
        self.assertIsNone(ZaloController._extract_file_info(None))

    def test_has_download_url(self):
        self.assertTrue(ZaloController._has_download_url({"href": "http://example.com/file"}))
        self.assertTrue(ZaloController._has_download_url({"url": "http://example.com/file"}))
        self.assertFalse(ZaloController._has_download_url({"title": "no_url"}))
        self.assertFalse(ZaloController._has_download_url({}))
        self.assertFalse(ZaloController._has_download_url("string"))

    def test_add_simulated_file_noop(self):
        ctrl = ZaloController()
        gf = GroupFile("id1", "mid1", "f.txt", 100, "G")
        ctrl.add_simulated_file(gf)

    # --- _extract_file_info fileSize parsing ---

    def test_extract_file_info_parses_file_size_from_params(self):
        content = {
            "href": "https://cdn/file.pdf",
            "title": "file.pdf",
            "params": '{"fileSize": 2048, "name": "file.pdf"}'
        }
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info, ("https://cdn/file.pdf", "file.pdf", 2048))

    def test_extract_file_info_bad_params_defaults_size_zero(self):
        content = {
            "href": "https://cdn/a.zip",
            "title": "a.zip",
            "params": "not json at all"
        }
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[2], 0)

    def test_extract_file_info_params_dict_ignored(self):
        # The bridge sends params as a JSON string; dict params are not parsed
        content = {
            "href": "https://cdn/b.png",
            "title": "b.png",
            "params": {"fileSize": 999}
        }
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[2], 0)

    def test_extract_file_info_params_json_list_ignored(self):
        content = {
            "href": "https://cdn/c.png",
            "title": "c.png",
            "params": '[1, 2, 3]'
        }
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[2], 0)

    def test_extract_file_info_title_falls_back_to_url_basename(self):
        content = {"href": "https://cdn/cat.gif?token=abc"}
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[1], "cat.gif")

    def test_extract_file_info_url_alternative_key(self):
        content = {"url": "https://cdn/dog.jpg", "title": ""}
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[0], "https://cdn/dog.jpg")

    def test_extract_file_info_missing_title_uses_file(self):
        content = {"href": "https://cdn/x.mp4"}
        info = ZaloController._extract_file_info(content)
        self.assertEqual(info[1], "x.mp4")

    # --- simple public helpers ---

    def test_is_zalo_running_reflects_connection(self):
        ctrl = ZaloController()
        self.assertFalse(ctrl.is_zalo_running())
        ctrl.is_connected = True
        self.assertTrue(ctrl.is_zalo_running())

    def test_get_qr_image_path_returns_constant(self):
        ctrl = ZaloController()
        self.assertEqual(ctrl.get_qr_image_path(), QR_FILE)

    def test_read_stderr_without_process(self):
        ctrl = ZaloController()
        self.assertEqual(ctrl._read_stderr(), "")

    def test_stop_bridge_without_process(self):
        ctrl = ZaloController()
        ctrl._stop_bridge()  # must not raise

    # --- event queue helpers ---

    def test_wait_for_event_found_and_removed(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._events = [{"event": "other", "x": 1}, {"event": "qrcode", "y": 2}]
        evt = ctrl._wait_for_event("qrcode", timeout=0.5)
        self.assertEqual(evt, {"event": "qrcode", "y": 2})
        self.assertEqual(ctrl._events, [{"event": "other", "x": 1}])

    def test_wait_for_event_timeout_returns_none(self):
        ctrl = ZaloController()
        ctrl._running = True
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            evt = ctrl._wait_for_event("never", timeout=0.01)
        self.assertIsNone(evt)

    def test_consume_events_filters_and_removes(self):
        ctrl = ZaloController()
        ctrl._events = [
            {"event": "login_error", "data": {"message": "bad"}},
            {"event": "qrcode", "data": {}},
            {"event": "login_error", "data": {"message": "again"}},
        ]
        consumed = ctrl._consume_events("login_error")
        self.assertEqual(len(consumed), 2)
        self.assertEqual(ctrl._events, [{"event": "qrcode", "data": {}}])

    def test_consume_events_no_match(self):
        ctrl = ZaloController()
        ctrl._events = [{"event": "qrcode"}]
        self.assertEqual(ctrl._consume_events("login_error"), [])
        self.assertEqual(len(ctrl._events), 1)

    # --- download flow (event-based, non-blocking) ---

    def test_effective_download_timeout_scaling(self):
        self.assertEqual(ZaloController._effective_download_timeout(0, 60), 60)
        self.assertEqual(ZaloController._effective_download_timeout(1024, 60), 60)
        # 1 GB -> scaled ~10000s, larger than any configured floor
        self.assertEqual(ZaloController._effective_download_timeout(10 ** 9, 60), 10000)
        self.assertEqual(ZaloController._effective_download_timeout(10 ** 9, 300), 10000)

    def test_download_waits_for_completion_event(self):
        ctrl = ZaloController()
        ctrl._running = True
        gf = GroupFile("fid1", "msg1", "big.mp4", 500 * 1024 * 1024, "G")
        dest = os.path.join(self.test_dir, "big.mp4")
        ctrl._message_url_map["msg1"] = ("https://cdn/big.mp4", "big.mp4", 500 * 1024 * 1024)
        with patch("zalo_drive_sync.services.zalo_controller.wait_for_file_stability", return_value=True):
            with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                       return_value={"status": "ok", "data": {"started": True, "path": dest}}) as mock_send:
                ctrl._events = [{"event": "download_complete", "data": {"id": "1", "path": dest, "size": 123}}]
                result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertEqual(result, dest)
        mock_send.assert_called_once_with(
            "download", {"url": "https://cdn/big.mp4", "destination": dest}, timeout=15)

    def test_download_error_event_returns_none(self):
        ctrl = ZaloController()
        ctrl._running = True
        gf = GroupFile("fid1", "msg1", "big.mp4", 100, "G")
        dest = os.path.join(self.test_dir, "big.mp4")
        ctrl._message_url_map["msg1"] = ("https://cdn/big.mp4", "big.mp4", 100)
        with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                   return_value={"status": "ok", "data": {"started": True, "path": dest}}):
            ctrl._events = [{"event": "download_complete", "data": {"id": "1", "path": dest, "error": "HTTP 403"}}]
            result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertIsNone(result)

    def test_download_timeout_returns_none(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "msg1", "big.mp4", 500 * 1024 * 1024, "G")
        dest = os.path.join(self.test_dir, "big.mp4")
        ctrl._message_url_map["msg1"] = ("https://cdn/big.mp4", "big.mp4", 500 * 1024 * 1024)
        with patch("zalo_drive_sync.services.zalo_controller.ZaloController._send_command",
                   return_value={"status": "ok", "data": {"started": True, "path": dest}}):
            with patch.object(ctrl, "_wait_for_download_event", return_value=None):
                with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
                    result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertIsNone(result)

    # --- _send_command ---

    def test_send_command_write_error_returns_none(self):
        ctrl = ZaloController()
        ctrl._process = MagicMock()
        ctrl._process.poll.return_value = None
        ctrl._process.stdin.write.side_effect = OSError("pipe closed")
        result = ctrl._send_command("get_status", timeout=1)
        self.assertIsNone(result)
        self.assertEqual(ctrl._pending, {})

    def test_send_command_success(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._process = MagicMock()
        ctrl._process.poll.return_value = None
        def fake_write(data):
            payload = json.loads(data)
            ctrl._pending[payload["id"]] = {"id": payload["id"], "status": "ok"}
            return len(data)
        ctrl._process.stdin.write.side_effect = fake_write
        result = ctrl._send_command("get_status", timeout=2)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")

    def test_send_command_bridge_dead_restarts(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._process = MagicMock()
        ctrl._process.poll.return_value = 1
        with patch("zalo_drive_sync.services.zalo_controller.ZaloController._stop_bridge") as mock_stop, \
             patch("zalo_drive_sync.services.zalo_controller.ZaloController._start_bridge") as mock_start:
            result = ctrl._send_command("get_status", timeout=1)
        self.assertIsNone(result)
        mock_stop.assert_called_once()
        mock_start.assert_called_once()

    def test_send_command_timeout_returns_none(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._process = MagicMock()
        ctrl._process.poll.return_value = None
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            result = ctrl._send_command("get_status", timeout=0.01)
        self.assertIsNone(result)
        self.assertEqual(ctrl._pending, {})

    def test_abort_waiting_interrupts_send_command(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        ctrl._process = proc
        ctrl.abort_waiting()
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            result = ctrl._send_command("get_status", timeout=5)
        self.assertIsNone(result)
        self.assertEqual(ctrl._pending, {})

    def test_clear_abort_allows_command(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        ctrl._process = proc
        ctrl._pending = {}
        ctrl.abort_waiting()
        ctrl.clear_abort()

        def deliver_response():
            with ctrl._lock:
                ctrl._pending["1"] = {"status": "ok"}

        ctrl._cmd_id = 0
        import threading as _t
        _t.Timer(0.05, deliver_response).start()
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            result = ctrl._send_command("get_status", timeout=5)
        self.assertEqual(result, {"status": "ok"})

    def test_wait_for_event_aborts(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl.abort_waiting()
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            result = ctrl._wait_for_event("qrcode", timeout=5)
        self.assertIsNone(result)

    def test_ensure_zalo_running_clears_abort(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.poll.return_value = None
        ctrl._process = proc
        ctrl.is_connected = True
        ctrl.abort_waiting()
        self.assertTrue(ctrl.ensure_zalo_running())
        self.assertFalse(ctrl._abort_event.is_set())

    # --- _wait_qr_login ---

    def test_wait_qr_login_direct_ok(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "ok"}):
            self.assertTrue(ctrl._wait_qr_login())

    def test_wait_qr_login_unexpected_response(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "weird"}):
            self.assertFalse(ctrl._wait_qr_login())

    def test_wait_qr_login_qr_flow_success(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "qr_started"}), \
             patch.object(ctrl, "_wait_for_event", side_effect=[{"event": "qrcode"}, {"event": "login_ok"}]):
            self.assertTrue(ctrl._wait_qr_login())

    def test_wait_qr_login_login_error(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "qr_started"}), \
             patch.object(ctrl, "_wait_for_event", side_effect=[{"event": "qrcode"}, None]), \
             patch.object(ctrl, "_consume_events", return_value=[{"data": {"message": "denied"}}]):
            self.assertFalse(ctrl._wait_qr_login())

    def test_wait_qr_login_no_qrcode_event(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "qr_started"}), \
             patch.object(ctrl, "_wait_for_event", return_value=None):
            self.assertFalse(ctrl._wait_qr_login())

    def test_wait_qr_login_invokes_qrcode_callback(self):
        seen = []
        ctrl = ZaloController(qrcode_callback=lambda p: seen.append(p))
        with patch.object(ctrl, "_send_command", return_value={"status": "qr_started"}), \
             patch.object(ctrl, "_wait_for_event", side_effect=[{"event": "qrcode"}, {"event": "login_ok"}]):
            self.assertTrue(ctrl._wait_qr_login())
        self.assertEqual(seen, [ctrl.get_qr_image_path()])

    def test_wait_qr_login_no_error_events_falls_through(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_send_command", return_value={"status": "qr_started"}), \
             patch.object(ctrl, "_wait_for_event", side_effect=[{"event": "qrcode"}, None]), \
             patch.object(ctrl, "_consume_events", return_value=[]):
            self.assertFalse(ctrl._wait_qr_login())

    # --- ensure_zalo_running ---

    def test_ensure_zalo_running_already_connected(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.poll.return_value = None
        ctrl._process = proc
        ctrl.is_connected = True
        self.assertTrue(ctrl.ensure_zalo_running())

    def test_ensure_zalo_running_reconnects_after_process_death(self):
        ctrl = ZaloController()
        dead = MagicMock()
        dead.poll.return_value = 1
        ctrl._process = dead
        ctrl.is_connected = True
        with patch.object(ctrl, "_stop_bridge") as mock_stop, \
             patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": True}}):
            self.assertTrue(ctrl.ensure_zalo_running())
        mock_stop.assert_called_once()
        self.assertTrue(ctrl.is_connected)

    def test_ensure_zalo_running_bridge_fails(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=False):
            self.assertFalse(ctrl.ensure_zalo_running())

    def test_ensure_zalo_running_already_logged_in(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": True}}):
            self.assertTrue(ctrl.ensure_zalo_running())
        self.assertTrue(ctrl.is_connected)

    def test_ensure_zalo_running_flow_success(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": False}}), \
             patch.object(ctrl, "has_saved_session", return_value=True), \
             patch.object(ctrl, "_wait_qr_login", return_value=True):
            self.assertTrue(ctrl.ensure_zalo_running())
        self.assertTrue(ctrl.is_connected)

    def test_ensure_zalo_running_flow_fails(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": False}}), \
             patch.object(ctrl, "has_saved_session", return_value=False), \
             patch.object(ctrl, "_wait_qr_login", return_value=False):
            self.assertFalse(ctrl.ensure_zalo_running())
        self.assertFalse(ctrl.is_connected)

    def test_ensure_zalo_running_no_cookie_qr_flow_success(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": False}}), \
             patch.object(ctrl, "has_saved_session", return_value=False), \
             patch.object(ctrl, "_wait_qr_login", return_value=True):
            self.assertTrue(ctrl.ensure_zalo_running())
        self.assertTrue(ctrl.is_connected)

    def test_ensure_zalo_running_cookie_login_fails(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_start_bridge", return_value=True), \
             patch.object(ctrl, "_send_command", return_value={"data": {"loggedIn": False}}), \
             patch.object(ctrl, "has_saved_session", return_value=True), \
             patch.object(ctrl, "_wait_qr_login", return_value=False):
            self.assertFalse(ctrl.ensure_zalo_running())
        self.assertFalse(ctrl.is_connected)

    # --- open_group ---

    def test_open_group_already_active(self):
        ctrl = ZaloController()
        ctrl.active_group = "G"
        ctrl._active_group_id = "gid"
        self.assertTrue(ctrl.open_group("G"))

    def test_open_group_cached_id(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        ctrl._group_name_to_id["G"] = "gid99"
        self.assertTrue(ctrl.open_group("G"))
        self.assertEqual(ctrl._active_group_id, "gid99")
        self.assertEqual(ctrl.active_group, "G")

    def test_open_group_not_connected_fails(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "ensure_zalo_running", return_value=False):
            self.assertFalse(ctrl.open_group("G"))

    def test_open_group_find_group_ok(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={"status": "ok", "data": {"groupId": "gidX"}}):
            self.assertTrue(ctrl.open_group("G"))
        self.assertEqual(ctrl._group_name_to_id["G"], "gidX")

    def test_open_group_find_group_fails(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value=None):
            self.assertFalse(ctrl.open_group("G"))

    def test_open_group_find_group_no_id(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={"status": "ok", "data": {}}):
            self.assertFalse(ctrl.open_group("G"))

    # --- _BASE_DIR frozen / log helper ---

    def test_base_dir_uses_executable_when_frozen(self):
        # Verified in a fresh interpreter so the module-level _BASE_DIR branch
        # is exercised without reloading the module in this test process.
        code = (
            "import sys; sys.frozen = True; sys.executable = r'C:\\App\\ZaloPCSyncDrive.exe';\n"
            "import zalo_drive_sync.services.zalo_controller as m;\n"
            "assert m._BASE_DIR == r'C:\\App', m._BASE_DIR\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=self.test_dir,
            env={**os.environ, "PYTHONPATH": os.pathsep.join([r"D:\AI", os.environ.get("PYTHONPATH", "")])}
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_log_invokes_logger_and_callback(self):
        seen = []
        ctrl = ZaloController(log_callback=lambda lvl, msg: seen.append((lvl, msg)))
        with patch("zalo_drive_sync.services.zalo_controller.logger") as mock_logger:
            ctrl.log("INFO", "hello")
        mock_logger.log.assert_called_once()
        self.assertEqual(seen, [("INFO", "hello")])

    # --- bridge lifecycle internals ---

    def test_start_bridge_locked_reuses_running_process(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.poll.return_value = None
        ctrl._process = proc
        with patch.object(ctrl, "_kill_orphan_bridges") as mock_kill:
            self.assertTrue(ctrl._start_bridge_locked())
        mock_kill.assert_not_called()

    @patch("zalo_drive_sync.services.zalo_controller.subprocess.Popen")
    def test_start_bridge_locked_success(self, mock_popen):
        ctrl = ZaloController()
        mock_popen.return_value.poll.return_value = None
        with patch.object(ctrl, "_read_stdout"), \
             patch.object(ctrl, "_wait_for_event", return_value={"event": "ready"}):
            self.assertTrue(ctrl._start_bridge_locked())
        self.assertTrue(ctrl._running)
        self.assertIsNotNone(ctrl._process)

    @patch("zalo_drive_sync.services.zalo_controller.subprocess.Popen")
    def test_start_bridge_locked_no_ready_event(self, mock_popen):
        ctrl = ZaloController()
        mock_popen.return_value.poll.return_value = None
        with patch.object(ctrl, "_read_stdout"), \
             patch.object(ctrl, "_wait_for_event", return_value=None), \
             patch.object(ctrl, "_read_stderr", return_value="boom"):
            self.assertFalse(ctrl._start_bridge_locked())
        self.assertFalse(ctrl.is_connected)

    def test_start_bridge_locked_popen_exception(self):
        ctrl = ZaloController()
        with patch("zalo_drive_sync.services.zalo_controller.subprocess.Popen",
                   side_effect=RuntimeError("boom")):
            self.assertFalse(ctrl._start_bridge_locked())

    def test_kill_orphan_bridges_kills_leftovers(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.pid = 999
        ctrl._process = proc
        ps_mock = MagicMock()
        ps_mock.stdout = "100\n999\n200\n"
        with patch("zalo_drive_sync.services.zalo_controller.subprocess.run",
                   return_value=ps_mock) as mock_run:
            ctrl._kill_orphan_bridges()
        # taskkill called for 100 and 200 but NOT 999 (own pid)
        taskkills = [c for c in mock_run.call_args_list if c.args[0][0] == "taskkill"]
        self.assertEqual(len(taskkills), 2)
        pids = [c.args[0][2] for c in taskkills]
        self.assertEqual(pids, ["100", "200"])

    def test_kill_orphan_bridges_ignores_noise_and_errors(self):
        ctrl = ZaloController()
        ps_mock = MagicMock()
        ps_mock.stdout = "not_a_pid\n\n123abc\n"
        with patch("zalo_drive_sync.services.zalo_controller.subprocess.run",
                   return_value=ps_mock) as mock_run:
            ctrl._kill_orphan_bridges()
        self.assertEqual(mock_run.call_count, 1)

    def test_kill_orphan_bridges_powershell_fails_silently(self):
        ctrl = ZaloController()
        with patch("zalo_drive_sync.services.zalo_controller.subprocess.run",
                   side_effect=Exception("denied")):
            ctrl._kill_orphan_bridges()  # must not raise

    def test_kill_orphan_bridges_taskkill_failure_swallowed(self):
        ctrl = ZaloController()
        ps_mock = MagicMock()
        ps_mock.stdout = "123\n"

        def fake_run(cmd, *args, **kwargs):
            if cmd[0] == "powershell":
                return ps_mock
            raise OSError("taskkill denied")

        with patch("zalo_drive_sync.services.zalo_controller.subprocess.run", side_effect=fake_run):
            ctrl._kill_orphan_bridges()  # must not raise

    def test_read_stderr_with_process(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.stderr = io.StringIO("some error")
        ctrl._process = proc
        self.assertEqual(ctrl._read_stderr(), "some error")

    def test_read_stderr_read_raises_returns_empty(self):
        ctrl = ZaloController()
        proc = MagicMock()
        proc.stderr.read.side_effect = OSError("gone")
        ctrl._process = proc
        self.assertEqual(ctrl._read_stderr(), "")

    def test_read_stdout_routes_response_and_event(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        lines = [
            '{"type": "response", "id": "7", "status": "ok"}',
            '{"type": "event", "event": "qrcode", "data": {}}',
            'not json',
            "",
        ]
        proc.stdout.readline.side_effect = lines
        ctrl._process = proc
        ctrl._pending["7"] = None
        ctrl._read_stdout()
        self.assertEqual(ctrl._pending["7"]["status"], "ok")
        self.assertTrue(any(e.get("event") == "qrcode" for e in ctrl._events))

    def test_read_stdout_skips_blank_and_unknown(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        lines = [
            '   ',
            '{"type": "response", "id": "99", "status": "ok"}',
            '{"type": "event", "event": "new_message", "data": {}}',
            "",
        ]
        proc.stdout.readline.side_effect = lines
        ctrl._process = proc
        ctrl._read_stdout()  # unknown response id + unconsumed event dropped
        self.assertEqual(ctrl._events, [])
        self.assertNotIn("99", ctrl._pending)

    def test_read_stdout_breaks_on_reader_exception(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        proc.stdout.readline.side_effect = OSError("pipe closed")
        ctrl._process = proc
        ctrl._read_stdout()  # generic exception -> break, must not raise

    def test_read_stdout_with_no_process_exits(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._process = None
        ctrl._read_stdout()  # while condition false -> immediate exit

    def test_read_stdout_trims_events_over_limit(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        payloads = [f'{{"type": "event", "event": "qrcode", "n": {i}}}' for i in range(250)]
        payloads.append("")
        proc.stdout.readline.side_effect = payloads
        ctrl._process = proc
        ctrl._read_stdout()
        self.assertLessEqual(len(ctrl._events), 200)

    def test_stop_bridge_terminates_process(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        ctrl._process = proc
        ctrl._reader_thread = MagicMock()
        ctrl._reader_thread.is_alive.return_value = True
        ctrl._stop_bridge()
        self.assertFalse(ctrl._running)
        proc.terminate.assert_called_once()

    def test_stop_bridge_kills_on_terminate_failure(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        proc.terminate.side_effect = Exception("nope")
        proc.wait.side_effect = Exception("nope")
        ctrl._process = proc
        ctrl._stop_bridge()
        proc.kill.assert_called_once()

    def test_stop_bridge_swallows_kill_failure(self):
        ctrl = ZaloController()
        ctrl._running = True
        proc = MagicMock()
        proc.terminate.side_effect = Exception("nope")
        proc.wait.side_effect = Exception("nope")
        proc.kill.side_effect = Exception("nope too")
        ctrl._process = proc
        ctrl._stop_bridge()  # must not raise
        self.assertIsNone(ctrl._process)

    def test_abort_waiting_and_clear(self):
        ctrl = ZaloController()
        ctrl.abort_waiting()
        self.assertTrue(ctrl._abort_event.is_set())
        ctrl.clear_abort()
        self.assertFalse(ctrl._abort_event.is_set())

    # --- list_groups ---

    def test_list_groups_not_connected_returns_empty(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "ensure_zalo_running", return_value=False):
            self.assertEqual(ctrl.list_groups(), [])

    def test_list_groups_error_response(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={"status": "error"}):
            self.assertEqual(ctrl.list_groups(), [])

    def test_list_groups_success(self):
        ctrl = ZaloController()
        ctrl.is_connected = True

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_groups":
                return {"status": "ok", "data": {"groupIds": ["g1", "g2", "g3"]}}
            if cmd == "get_group_info":
                return {"status": "ok", "data": {
                    "gridInfoMap": {"g1": {"name": "Alpha"}, "g2": {"name": "Beta"}}
                }}
            return None

        with patch.object(ctrl, "_send_command", side_effect=fake_send):
            groups = ctrl.list_groups()
        self.assertEqual(groups, [("Alpha", "g1"), ("Beta", "g2")])

    def test_list_groups_skips_missing_names(self):
        ctrl = ZaloController()
        ctrl.is_connected = True

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_groups":
                return {"status": "ok", "data": {"groupIds": ["g1"]}}
            if cmd == "get_group_info":
                return {"status": "ok", "data": {"gridInfoMap": {"g1": {}}}}
            return None

        with patch.object(ctrl, "_send_command", side_effect=fake_send):
            groups = ctrl.list_groups()
        self.assertEqual(groups, [])

    def test_list_groups_skips_failed_info_lookups(self):
        ctrl = ZaloController()
        ctrl.is_connected = True

        def fake_send(cmd, data=None, timeout=30):
            if cmd == "get_groups":
                return {"status": "ok", "data": {"groupIds": ["g1", "g2"]}}
            if cmd == "get_group_info":
                return {"status": "error"}
            return None

        with patch.object(ctrl, "_send_command", side_effect=fake_send):
            groups = ctrl.list_groups()
        self.assertEqual(groups, [])

    def test_list_groups_respects_max(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command",
                          return_value={"status": "ok", "data": {"groupIds": ["a", "b", "c"]}}):
            groups = ctrl.list_groups(max_groups=1)
        self.assertEqual(len(groups), 0)  # info lookups return nothing

    def test_persist_cursors_no_config_is_noop(self):
        ctrl = ZaloController()  # config_manager=None
        ctrl._last_seen_msg_id["g"] = "1"
        ctrl._persist_cursors()  # must not raise

    def test_persist_cursors_merges_existing(self):
        config_mock = MagicMock()
        config_mock.get.return_value = {"old": "9"}
        ctrl = ZaloController(config_manager=config_mock)
        ctrl._last_seen_msg_id["new"] = "5"
        ctrl._persist_cursors()
        _, value = config_mock.set.call_args[0]
        self.assertEqual(value, {"old": "9", "new": "5"})

    def test_init_ignores_bad_config_cursor(self):
        config_mock = MagicMock()
        config_mock.get.side_effect = RuntimeError("bad")
        ctrl = ZaloController(config_manager=config_mock)
        self.assertEqual(ctrl._last_seen_msg_id, {})

    def test_init_ignores_non_dict_cursor(self):
        config_mock = MagicMock()
        config_mock.get.return_value = ["not", "a", "dict"]
        ctrl = ZaloController(config_manager=config_mock)
        self.assertEqual(ctrl._last_seen_msg_id, {})

    def test_persist_cursors_swallows_config_error(self):
        config_mock = MagicMock()
        config_mock.set.side_effect = RuntimeError("disk full")
        ctrl = ZaloController(config_manager=config_mock)
        ctrl._last_seen_msg_id["g"] = "1"
        ctrl._persist_cursors()  # must not raise

    # --- download edge cases ---

    def test_download_no_url_returns_none(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "missing_msg", "ghost.pdf", 100, "G")
        self.assertIsNone(ctrl.download_group_file(gf, self.test_dir))

    def test_download_falls_back_to_filename_match(self):
        ctrl = ZaloController()
        ctrl._running = True
        gf = GroupFile("fid1", "unknown_msg_id", "doc.pdf", 100, "G")
        dest = os.path.join(self.test_dir, "doc.pdf")
        ctrl._message_url_map["other_msg"] = ("https://cdn/doc.pdf", "doc.pdf", 100)
        with patch("zalo_drive_sync.services.zalo_controller.wait_for_file_stability", return_value=True):
            with patch.object(ctrl, "_send_command",
                              return_value={"status": "ok", "data": {"started": True, "path": dest}}):
                ctrl._events = [{"event": "download_complete", "data": {"path": dest}}]
                result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertEqual(result, dest)

    def test_download_falls_back_no_filename_match_returns_none(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "unknown_msg_id", "ghost.pdf", 100, "G")
        ctrl._message_url_map["other_msg"] = ("https://cdn/other.pdf", "other.pdf", 100)
        self.assertIsNone(ctrl.download_group_file(gf, self.test_dir))

    def test_download_waits_skips_non_matching_event(self):
        ctrl = ZaloController()
        ctrl._running = True
        gf = GroupFile("fid1", "msg1", "f.pdf", 100, "G")
        dest = os.path.join(self.test_dir, "f.pdf")
        ctrl._message_url_map["msg1"] = ("https://cdn/f.pdf", "f.pdf", 100)
        with patch("zalo_drive_sync.services.zalo_controller.wait_for_file_stability", return_value=True):
            with patch.object(ctrl, "_send_command",
                              return_value={"status": "ok", "data": {"started": True, "path": dest}}):
                ctrl._events = [
                    {"event": "download_complete", "data": {"path": os.path.join(self.test_dir, "other.pdf")}},
                    {"event": "download_complete", "data": {"path": dest}},
                ]
                result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertEqual(result, dest)

    def test_download_start_failed_returns_none(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "msg1", "f.pdf", 100, "G")
        ctrl._message_url_map["msg1"] = ("https://cdn/f.pdf", "f.pdf", 100)
        with patch.object(ctrl, "_send_command",
                          return_value={"status": "error", "data": {"message": "denied"}}):
            result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertIsNone(result)

    def test_download_stability_failed_returns_none(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "msg1", "f.pdf", 100, "G")
        dest = os.path.join(self.test_dir, "f.pdf")
        ctrl._message_url_map["msg1"] = ("https://cdn/f.pdf", "f.pdf", 100)
        with patch.object(ctrl, "_send_command",
                          return_value={"status": "ok", "data": {"started": True, "path": dest}}), \
             patch.object(ctrl, "_wait_for_download_event",
                          return_value={"data": {"path": dest, "size": 100}}), \
             patch("zalo_drive_sync.services.zalo_controller.wait_for_file_stability",
                   return_value=False):
            result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertIsNone(result)

    def test_download_stability_raises_path_missing(self):
        ctrl = ZaloController()
        gf = GroupFile("fid1", "msg1", "f.pdf", 100, "G")
        ctrl._message_url_map["msg1"] = ("https://cdn/f.pdf", "f.pdf", 100)
        with patch.object(ctrl, "_send_command",
                          return_value={"status": "ok", "data": {"started": True, "path": "x"}}), \
             patch.object(ctrl, "_wait_for_download_event", return_value={"data": {"path": "x"}}), \
             patch("zalo_drive_sync.services.zalo_controller.wait_for_file_stability",
                   return_value=True):
            result = ctrl.download_group_file(gf, self.test_dir, timeout=60)
        self.assertEqual(result, "x")

    def test_wait_for_download_event_timeout(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._events = []
        with patch("zalo_drive_sync.services.zalo_controller.time.sleep"):
            self.assertIsNone(ctrl._wait_for_download_event("nope", 0.01))

    def test_wait_for_download_event_finds_match(self):
        ctrl = ZaloController()
        ctrl._running = True
        ctrl._events = [{"event": "download_complete", "data": {"path": "/x"}}]
        evt = ctrl._wait_for_download_event("/x", 0.5)
        self.assertEqual(evt["event"], "download_complete")
        self.assertEqual(ctrl._events, [])

    def test_del_calls_stop_bridge(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "_stop_bridge") as mock_stop:
            ctrl.__del__()
        mock_stop.assert_called_once()

    def test_get_group_id_by_name_cached(self):
        ctrl = ZaloController()
        ctrl._group_name_to_id["Alpha"] = "gid-cached"
        self.assertEqual(ctrl.get_group_id_by_name("Alpha"), "gid-cached")

    def test_get_group_id_by_name_not_connected(self):
        ctrl = ZaloController()
        ctrl.is_connected = False
        with patch.object(ctrl, "ensure_zalo_running", return_value=False):
            self.assertIsNone(ctrl.get_group_id_by_name("Alpha"))

    def test_get_group_id_by_name_from_bridge(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={
            "status": "ok", "data": {"groupId": "gid-1"}
        }) as mock_send:
            self.assertEqual(ctrl.get_group_id_by_name("Alpha"), "gid-1")
            self.assertEqual(ctrl._group_name_to_id["Alpha"], "gid-1")
            mock_send.assert_called_once()

    def test_get_group_id_by_name_bridge_fail(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={"status": "error"}):
            self.assertIsNone(ctrl.get_group_id_by_name("Alpha"))

    def test_get_group_members_ok(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        payload = {"status": "ok", "data": {"members": [{"id": "u1", "name": "An"}]}}
        with patch.object(ctrl, "_send_command", return_value=payload) as mock_send:
            out = ctrl.get_group_members("g1", 100)
        self.assertEqual(out, [{"id": "u1", "name": "An"}])
        mock_send.assert_called_once_with("get_members", {"groupId": "g1", "count": 100}, timeout=120)

    def test_get_group_members_fail(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value=None):
            self.assertEqual(ctrl.get_group_members("g1"), [])

    def test_kick_group_members_ok(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={
            "status": "ok", "data": {"errorMembers": []}}) as mock_send:
            self.assertEqual(ctrl.kick_group_members("g1", ["u1", "u2"]), [])
        mock_send.assert_called_once_with(
            "kick_members", {"groupId": "g1", "memberIds": ["u1", "u2"]}, timeout=60)

    def test_kick_group_members_partial(self):
        ctrl = ZaloController()
        ctrl.is_connected = True
        with patch.object(ctrl, "_send_command", return_value={
            "status": "ok", "data": {"errorMembers": ["u2"]}}):
            self.assertEqual(ctrl.kick_group_members("g1", ["u1", "u2"]), ["u2"])

    def test_kick_group_members_no_ids(self):
        ctrl = ZaloController()
        with patch.object(ctrl, "ensure_zalo_running") as mock_ensure:
            self.assertEqual(ctrl.kick_group_members("g1", []), [])
        mock_ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
