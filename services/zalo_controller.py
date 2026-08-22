import json
import os
import sys
import logging
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from datetime import datetime

from zalo_drive_sync.services.zalo_service import wait_for_file_stability

logger = logging.getLogger("ZaloPCSync")

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BRIDGE_DIR = os.path.join(_BASE_DIR, "node_bridge")
BRIDGE_SCRIPT = os.path.join(BRIDGE_DIR, "zalo_bridge.js")
COOKIE_FILE = os.path.join(BRIDGE_DIR, "cookie.json")
QR_FILE = os.path.join(BRIDGE_DIR, "qr.png")
NODE_BIN = "node"

FILE_MSG_TYPES = {"chat.photo", "share.file", "chat.video.msg", "chat.gif", "chat.voice"}

# Bridge events this controller actually consumes. Everything else (e.g. the
# high-frequency "new_message" stream) is dropped to avoid unbounded RAM growth.
_CONSUMED_EVENTS = {
    "ready", "qrcode", "qrcode_expired", "scanned", "qrcode_declined",
    "login_ok", "login_error", "download_complete",
}
_MAX_EVENTS = 200
_MAX_URL_MAP = 2000


class GroupFile:
    def __init__(
        self,
        file_id: str,
        message_id: str,
        filename: str,
        filesize: int,
        group_name: str,
        sender: str = "Member",
        created_time: Optional[str] = None
    ):
        self.file_id = file_id or f"zf_{uuid.uuid4().hex[:8]}"
        self.message_id = message_id or f"msg_{uuid.uuid4().hex[:8]}"
        self.filename = filename
        self.filesize = filesize
        self.group_name = group_name
        self.sender = sender
        self.created_time = created_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "message_id": self.message_id,
            "filename": self.filename,
            "filesize": self.filesize,
            "group_name": self.group_name,
            "sender": self.sender,
            "created_time": self.created_time
        }


class ZaloController:
    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None, qrcode_callback: Optional[Callable[[str], None]] = None, config_manager=None):
        self.log_callback = log_callback
        self.qrcode_callback = qrcode_callback
        self._config_manager = config_manager
        self.is_connected = False
        self.active_group: Optional[str] = None
        self._active_group_id: Optional[str] = None
        self._group_name_to_id: Dict[str, str] = {}
        self._message_url_map: Dict[str, Tuple[str, str, int]] = {}
        self._last_seen_msg_id: Dict[str, str] = {}
        self._last_cached_total: Dict[str, int] = {}

        # Restore the per-group scan cursor so a restart keeps catching up from
        # where the app last left off instead of only seeing the newest 50 msgs.
        if config_manager is not None:
            try:
                cursors = config_manager.get("last_seen_msg_ids") or {}
                if isinstance(cursors, dict):
                    self._last_seen_msg_id = {str(k): str(v) for k, v in cursors.items()}
            except Exception:
                pass

        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._bridge_lock = threading.RLock()
        self._abort_event = threading.Event()
        self._cmd_id = 0
        self._pending: Dict[str, Optional[Dict]] = {}
        self._events: List[Dict[str, Any]] = []
        self._events_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def log(self, level: str, message: str):
        logger.log(getattr(logging, level.upper(), logging.INFO), message)
        if self.log_callback:
            self.log_callback(level, message)

    # --- Bridge lifecycle ---

    def _start_bridge(self) -> bool:
        with self._bridge_lock:
            return self._start_bridge_locked()

    def _kill_orphan_bridges(self):
        """Kills leftover zalo_bridge.js node processes from crashed app instances."""
        try:
            ps = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
                 "Where-Object { $_.CommandLine -like '*zalo_bridge.js*' } | "
                 "ForEach-Object { $_.ProcessId }"],
                capture_output=True, text=True, timeout=15
            )
            for line in (ps.stdout or "").splitlines():
                pid = line.strip()
                if not pid.isdigit():
                    continue
                if self._process and str(self._process.pid) == pid:
                    continue
                try:
                    subprocess.run(["taskkill", "/PID", pid, "/F"],
                                   capture_output=True, timeout=10)
                    self.log("INFO", f"[Bridge] Killed orphan bridge process PID {pid}.")
                except Exception:
                    pass
        except Exception:
            pass

    def _start_bridge_locked(self) -> bool:
        if self._process and self._process.poll() is None:
            return True
        self._kill_orphan_bridges()
        self.log("INFO", "[Bridge] Starting Node.js Zalo API bridge...")
        try:
            self._process = subprocess.Popen(
                [NODE_BIN, "--max-old-space-size=2048", BRIDGE_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=BRIDGE_DIR,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
            self._reader_thread.start()
            ok = self._wait_for_event("ready", timeout=10)
            if ok:
                self.log("INFO", "[Bridge] Node.js bridge started.")
                return True
            stderr_out = self._read_stderr()
            self.log("ERROR", f"[Bridge] No ready event. stderr: {stderr_out}")
            return False
        except FileNotFoundError:
            self.log("ERROR", "[Bridge] Node.js not found. Install from https://nodejs.org")
            return False
        except Exception as e:
            self.log("ERROR", f"[Bridge] Failed: {e}")
            return False

    def _stop_bridge(self):
        with self._bridge_lock:
            self._running = False
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.0)
            self._reader_thread = None
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=3)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
                self._process = None

    def _read_stderr(self) -> str:
        if not self._process or not self._process.stderr:
            return ""
        try:
            return self._process.stderr.read(2000)
        except Exception:
            return ""

    def _read_stdout(self):
        while self._running and self._process and self._process.stdout:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("type") == "response":
                    rid = msg.get("id")
                    with self._lock:
                        if rid in self._pending:
                            self._pending[rid] = msg
                elif msg.get("type") == "event" and msg.get("event") in _CONSUMED_EVENTS:
                    with self._events_lock:
                        self._events.append(msg)
                        if len(self._events) > _MAX_EVENTS:
                            del self._events[:len(self._events) - _MAX_EVENTS]
            except (json.JSONDecodeError, ValueError):
                continue
            except Exception:
                break

    # --- Command / Event primitives ---

    def _send_command(self, command: str, data: Optional[Dict] = None, timeout: float = 30) -> Optional[Dict]:
        cmd_id = None
        with self._lock:
            self._cmd_id += 1
            cmd_id = str(self._cmd_id)
            self._pending[cmd_id] = None

        payload = json.dumps({"id": cmd_id, "command": command, "data": data or {}})
        proc = self._process
        if proc is None or proc.poll() is not None:
            with self._lock:
                self._pending.pop(cmd_id, None)
            self.log("ERROR", "[Bridge] Bridge process is not running. Restarting...")
            if self._running:
                self._stop_bridge()
                self._start_bridge()
            return None
        try:
            with self._write_lock:
                proc.stdin.write(payload + "\n")
                proc.stdin.flush()
        except Exception as e:
            with self._lock:
                self._pending.pop(cmd_id, None)
            self.log("ERROR", f"[Bridge] Write error: {e}")
            return None

        deadline = time.time() + timeout
        while self._running and not self._abort_event.is_set() and time.time() < deadline:
            with self._lock:
                result = self._pending.get(cmd_id)
                if result is not None:
                    self._pending.pop(cmd_id, None)
                    return result
            time.sleep(0.1)

        with self._lock:
            self._pending.pop(cmd_id, None)
        if not self._running or self._abort_event.is_set():
            self.log("DEBUG", f"[Bridge] Command '{command}' aborted (bridge stopped).")
        else:
            self.log("WARN", f"[Bridge] Command '{command}' timed out ({timeout}s)")
        return None

    def _wait_for_event(self, event_name: str, timeout: float = 30) -> Optional[Dict]:
        deadline = time.time() + timeout
        while self._running and not self._abort_event.is_set() and time.time() < deadline:
            with self._events_lock:
                for i, evt in enumerate(self._events):
                    if evt.get("event") == event_name:
                        self._events.pop(i)
                        return evt
            time.sleep(0.25)
        return None

    def _consume_events(self, event_name: str) -> List[Dict]:
        result = []
        with self._events_lock:
            remaining = []
            for evt in self._events:
                if evt.get("event") == event_name:
                    result.append(evt)
                else:
                    remaining.append(evt)
            self._events = remaining
        return result

    # --- Helpers ---

    @staticmethod
    def _extract_file_info(content: Any) -> Optional[Tuple[str, str, int]]:
        if not isinstance(content, dict):
            return None
        href = content.get("href") or content.get("url", "")
        title = content.get("title") or os.path.basename(href.split("?")[0]) if href else ""
        if not title:
            title = "file"
        filesize = 0
        try:
            params = content.get("params", "")
            if isinstance(params, str) and params:
                params_json = json.loads(params)
                if isinstance(params_json, dict):
                    filesize = int(params_json.get("fileSize") or 0)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
        if href and title:
            return (href, title, filesize)
        return None

    @staticmethod
    def _has_download_url(content: Any) -> bool:
        if isinstance(content, dict):
            return bool(content.get("href") or content.get("url"))
        return False

    # --- Public API ---

    def is_zalo_running(self) -> bool:
        return self.is_connected

    def has_saved_session(self) -> bool:
        return os.path.exists(COOKIE_FILE)

    def get_qr_image_path(self) -> str:
        return QR_FILE

    def _wait_qr_login(self) -> bool:
        resp = self._send_command("login", timeout=10)
        if resp and resp.get("status") == "ok":
            return True
        if resp and resp.get("status") != "qr_started":
            self.log("ERROR", f"[Login] Unexpected response: {resp}")
            return False

        qr_event = self._wait_for_event("qrcode", timeout=15)
        if qr_event:
            self.log("INFO", f"[Login] Scan QR code at: {self.get_qr_image_path()}")
            if self.qrcode_callback:
                self.qrcode_callback(self.get_qr_image_path())

            login_ok = self._wait_for_event("login_ok", timeout=120)
            if login_ok:
                self.log("INFO", "[Login] QR login successful.")
                return True

            login_err = self._consume_events("login_error")
            if login_err:
                err_msg = login_err[0].get("data", {}).get("message", "unknown")
                self.log("ERROR", f"[Login] QR login failed: {err_msg}")

        self.log("ERROR", "[Login] QR login failed or timed out.")
        return False

    def ensure_zalo_running(self) -> bool:
        with self._bridge_lock:
            self._abort_event.clear()
            if self.is_connected:
                if self._process and self._process.poll() is None:
                    return True
                self.log("WARNING", "[Bridge] Process died; reconnecting...")
                self.is_connected = False
                self._stop_bridge()
                with self._lock:
                    self._pending.clear()
                with self._events_lock:
                    self._events.clear()

            if not self._start_bridge():
                return False

            resp = self._send_command("get_status", timeout=10)
            already_logged = resp and resp.get("data", {}).get("loggedIn", False)

            if not already_logged:
                has_cookie = self.has_saved_session()
                self.log("INFO", f"[Login] Starting Zalo login (saved session: {has_cookie})...")
                if has_cookie:
                    if self._wait_qr_login():
                        self.is_connected = True
                        self.log("INFO", "[Login] Zalo connected.")
                        return True
                else:
                    self.log("INFO", "[Login] No saved session. Generating QR code for phone scan...")
                    if self._wait_qr_login():
                        self.is_connected = True
                        self.log("INFO", "[Login] Zalo connected.")
                        return True
                return False

            self.is_connected = True
            self.log("INFO", "[Login] Zalo connected.")
            return True

    def abort_waiting(self):
        self._abort_event.set()

    def clear_abort(self):
        self._abort_event.clear()

    def list_groups(self, max_groups: int = 100) -> List[Tuple[str, str]]:
        """Returns list of (group_name, group_id) for all visible Zalo groups."""
        if not self.is_connected and not self.ensure_zalo_running():
            return []

        self.log("INFO", "[Groups] Loading group list from Zalo...")
        resp = self._send_command("get_groups", timeout=15)
        if not resp or resp.get("status") != "ok":
            self.log("ERROR", f"[Groups] Failed to list groups: {resp}")
            return []

        group_ids = (resp.get("data") or {}).get("groupIds", [])[:max_groups]
        result: List[Tuple[str, str]] = []
        for gid in group_ids:
            info = self._send_command("get_group_info", {"groupId": gid}, timeout=15)
            if not info or info.get("status") != "ok":
                continue
            grid_map = (info.get("data") or {}).get("gridInfoMap") or {}
            entry = grid_map.get(gid) or {}
            name = entry.get("name") or ""
            if name:
                result.append((name, gid))

        self.log("INFO", f"[Groups] Loaded {len(result)} groups.")
        return result

    def open_group(self, group_name: str) -> bool:
        if self.active_group == group_name and self._active_group_id:
            return True
        if not self.is_connected and not self.ensure_zalo_running():
            return False

        if self._group_name_to_id.get(group_name):
            self._active_group_id = self._group_name_to_id[group_name]
            self.active_group = group_name
            return True

        self.log("INFO", f"[Group] Searching for '{group_name}'...")
        resp = self._send_command("find_group", {"name": group_name}, timeout=120)
        if not resp or resp.get("status") != "ok":
            self.log("ERROR", f"[Group] Failed to find '{group_name}': {resp}")
            return False

        gid = resp.get("data", {}).get("groupId")
        if not gid:
            self.log("ERROR", "[Group] No group ID returned.")
            return False

        self._group_name_to_id[group_name] = gid
        self._active_group_id = gid
        self.active_group = group_name
        self.log("INFO", f"[Group] Found: '{group_name}' (ID: {gid})")
        return True

    def get_group_id_by_name(self, group_name: str) -> Optional[str]:
        """Resolves a group name to its Zalo group ID, without switching active group."""
        if self._group_name_to_id.get(group_name):
            return self._group_name_to_id[group_name]
        if not self.is_connected and not self.ensure_zalo_running():
            return None
        resp = self._send_command("find_group", {"name": group_name}, timeout=120)
        if not resp or resp.get("status") != "ok":
            return None
        gid = resp.get("data", {}).get("groupId")
        if gid:
            self._group_name_to_id[group_name] = gid
        return gid or None

    def get_group_members(self, group_id: str, count: int = 2000) -> List[Dict[str, Any]]:
        """Fetches a group's member roster + last-active stats from the bridge."""
        if not self.is_connected and not self.ensure_zalo_running():
            return []
        self.log("INFO", f"[Members] Fetching member stats for group {group_id}...")
        resp = self._send_command("get_members", {"groupId": group_id, "count": count}, timeout=120)
        if not resp or resp.get("status") != "ok":
            self.log("ERROR", f"[Members] Failed to fetch: {resp}")
            return []
        return (resp.get("data") or {}).get("members", [])

    def kick_group_members(self, group_id: str, member_ids: List[str]) -> List[str]:
        """Kicks members from a group. Returns the members Zalo could not remove."""
        if not member_ids:
            return []
        if not self.is_connected and not self.ensure_zalo_running():
            return member_ids
        self.log("INFO", f"[Members] Kicking {len(member_ids)} member(s) from {group_id}...")
        resp = self._send_command(
            "kick_members", {"groupId": group_id, "memberIds": member_ids}, timeout=60
        )
        if not resp or resp.get("status") != "ok":
            self.log("ERROR", f"[Members] Kick failed: {resp}")
            return member_ids
        return (resp.get("data") or {}).get("errorMembers", []) or []

    def scan_group_files(self, group_name: str) -> List[GroupFile]:
        if self.active_group != group_name:
            if not self.open_group(group_name):
                return []

        self.log("INFO", f"[Scan] Requesting messages for '{group_name}'...")
        since_msg_id = self._last_seen_msg_id.get(self._active_group_id)
        self._send_command(
            "request_old_messages",
            {"groupId": self._active_group_id, "count": 300, "lastMsgId": since_msg_id},
            timeout=30
        )

        msg_resp = self._poll_group_messages(group_name, since_msg_id=since_msg_id)

        files: List[GroupFile] = []
        if not msg_resp or msg_resp.get("status") != "ok":
            return files

        messages = msg_resp.get("data", {}).get("messages", [])
        max_msg_id: Optional[int] = None
        for msg in messages:
            content = msg.get("content")
            if not content:
                continue
            info = self._extract_file_info(content)
            if info is None:
                continue

            href, title, filesize = info
            msg_id = msg.get("msgId", uuid.uuid4().hex[:12])
            sender = msg.get("sender", "Member")
            ts = msg.get("timestamp", 0)

            try:
                numeric_id = int(msg_id)
                if max_msg_id is None or numeric_id > max_msg_id:
                    max_msg_id = numeric_id
            except (ValueError, TypeError):
                pass

            msg_type = msg.get("msgType", "")
            ext_map = {
                "share.file": ".file", "chat.photo": ".jpg",
                "chat.video.msg": ".mp4", "chat.gif": ".gif",
                "chat.voice": ".mp3"
            }
            if "." not in title and msg_type in ext_map:
                title = title + ext_map[msg_type]

            self._message_url_map[msg_id] = (href, title, filesize)
            if len(self._message_url_map) > _MAX_URL_MAP:
                # Drop oldest entries to bound memory (dict preserves insertion order)
                excess = len(self._message_url_map) - _MAX_URL_MAP
                for old_key in list(self._message_url_map.keys())[:excess]:
                    del self._message_url_map[old_key]

            gf = GroupFile(
                file_id=msg_id[:12],
                message_id=msg_id,
                filename=title,
                filesize=filesize,
                group_name=group_name,
                sender=sender,
                created_time=(
                    datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    if ts else None
                )
            )
            files.append(gf)

        if max_msg_id is not None and self._active_group_id:
            self._last_seen_msg_id[self._active_group_id] = str(max_msg_id)
            self._persist_cursors()

        self.log("INFO", f"[Scan] Found {len(files)} files in '{group_name}'.")
        return files

    def _persist_cursors(self):
        """Writes the per-group scan cursor to config so restarts catch up fully."""
        if self._config_manager is None:
            return
        try:
            cursors = dict(self._config_manager.get("last_seen_msg_ids") or {})
            cursors.update(self._last_seen_msg_id)
            self._config_manager.set("last_seen_msg_ids", cursors)
        except Exception:
            pass

    def _poll_group_messages(self, group_name: str, max_wait: float = 20.0, since_msg_id: Optional[str] = None) -> Optional[Dict]:
        """Polls get_group_messages until the cached message count stabilizes.

        With delta sync (since_msg_id) the bridge only returns messages newer than
        the cursor, so the payload is small. We fast-exit when nothing changed
        since the last scan; otherwise poll until two consecutive reads return
        the same (non-decreasing) count, or until max_wait elapses.
        """
        group_id = self._active_group_id
        last_known_total = self._last_cached_total.get(group_id) if group_id else None
        prev_total = -1
        deadline = time.time() + max_wait
        best_resp: Optional[Dict] = None
        stable_rounds = 0

        while time.time() < deadline:
            resp = self._send_command(
                "get_group_messages",
                {
                    "groupId": group_id,
                    "types": list(FILE_MSG_TYPES),
                    "since_msg_id": since_msg_id
                },
                timeout=15
            )
            if resp and resp.get("status") == "ok":
                best_resp = resp
                data = resp.get("data", {})
                total = data.get("total", 0)
                new_count = data.get("new_count", total)
                if total == last_known_total and new_count == 0 and total > 0:
                    self.log("INFO", f"[Scan] No new files (cache unchanged, {total} cached).")
                    break
                if total == prev_total and total > 0:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        self.log("INFO", f"[Scan] Message cache stable ({total} cached).")
                        break
                elif total > 0:
                    stable_rounds = 0
                prev_total = total
            time.sleep(1.0)

        if best_resp and best_resp.get("status") == "ok":
            self._last_cached_total[group_id] = best_resp.get("data", {}).get("total", 0)
        return best_resp

    def add_simulated_file(self, group_file: GroupFile):
        pass

    @staticmethod
    def _effective_download_timeout(filesize: int, timeout: int) -> int:
        """Scales download wait time with file size so large files don't time out.

        Uses a ~100 KB/s floor baseline; never shorter than the configured timeout.
        """
        scaled = int(filesize / 100000) if filesize > 0 else 0
        return max(int(timeout), scaled)

    def _wait_for_download_event(self, dest_path: str, timeout: float) -> Optional[Dict]:
        deadline = time.time() + timeout
        while self._running and not self._abort_event.is_set() and time.time() < deadline:
            with self._events_lock:
                for i, evt in enumerate(self._events):
                    if evt.get("event") == "download_complete" and evt.get("data", {}).get("path") == dest_path:
                        self._events.pop(i)
                        return evt
            time.sleep(0.1)
        return None

    def download_group_file(
        self,
        group_file: GroupFile,
        download_folder: str,
        timeout: int = 60,
        destination_path: Optional[str] = None,
    ) -> Optional[str]:
        msg_id = group_file.message_id
        url_info = self._message_url_map.get(msg_id)

        if not url_info:
            for mid, (href, fname, fsize) in self._message_url_map.items():
                if fname == group_file.filename:
                    url_info = (href, fname, fsize)
                    break

        if not url_info:
            self.log("ERROR", f"[Download] No URL for '{group_file.filename}'.")
            return None

        href, fname, fsize = url_info
        os.makedirs(download_folder, exist_ok=True)
        dest_path = destination_path or os.path.join(
            download_folder, os.path.basename(group_file.filename)
        )

        self.log("INFO", f"[Download] Fetching '{group_file.filename}'...")
        resp = self._send_command("download", {"url": href, "destination": dest_path}, timeout=15)
        if not resp or resp.get("status") != "ok":
            err_msg = resp.get("data", {}).get("message", "timeout") if resp else "no response"
            self.log("ERROR", f"[Download] Failed to start: {err_msg}")
            return None

        effective_timeout = self._effective_download_timeout(fsize, timeout)
        self.log("INFO", f"[Download] Waiting up to {effective_timeout}s for '{group_file.filename}' ({fsize / (1024 * 1024):.1f} MB)...")
        event = self._wait_for_download_event(dest_path, effective_timeout)
        if not event:
            self.log("ERROR", f"[Download] Timed out after {effective_timeout}s waiting for '{group_file.filename}'.")
            return None

        data = event.get("data", {})
        if data.get("error"):
            self.log("ERROR", f"[Download] Failed: {data['error']}")
            return None

        dl_path = data.get("path", dest_path)
        if wait_for_file_stability(dl_path, check_interval=0.5, timeout=min(30.0, float(effective_timeout))):
            self.log("INFO", f"[Download] Complete: {group_file.filename}")
            return dl_path

        self.log("ERROR", f"[Download] Stability check failed for '{group_file.filename}'.")
        return None

    def __del__(self):
        self._stop_bridge()
