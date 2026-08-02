"""
Auto-update Module
Checks for newer versions (JSON feed or GitHub Releases API), downloads the
portable zip, stages it, and applies it via a .cmd script that swaps files
after the running app exits.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from typing import Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    logger = None

DEFAULT_TIMEOUT = 30
_UPDATE_DIR_NAME = "_updates"


def get_current_version() -> str:
    """Returns the current application version from package metadata."""
    try:
        from zalo_drive_sync import __version__
        return str(__version__)
    except Exception:
        return "0.0.0"


def parse_version(version: str) -> Tuple[int, int, int]:
    """Parses 'X.Y.Z' (allowing a leading 'v') into an int tuple."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(version))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def is_newer_version(candidate: str, reference: str) -> bool:
    """True if candidate is semantically newer than reference."""
    return parse_version(candidate) > parse_version(reference)


def _http_get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[Dict]:
    """Fetches and decodes a JSON document from a URL. Returns None on failure."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ZaloPCSyncDrive-Updater/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        if logger:
            logger.error(f"Update check failed for {url}: {exc}")
        return None


def check_for_update(update_url: str, current_version: str) -> Optional[Dict]:
    """
    Checks a custom JSON feed. Expected shape:
        {"version": "1.1.6", "download_url": "https://.../app.zip", "notes": "..."}
    Returns a normalized dict, or None when unavailable / not newer.
    """
    if not update_url:
        return None
    data = _http_get_json(update_url)
    if not data or not data.get("version"):
        return None
    version = str(data["version"])
    if not is_newer_version(version, current_version):
        return None
    return {
        "version": version,
        "download_url": str(data.get("download_url", "")),
        "notes": str(data.get("notes", "")),
    }


def check_github_release(repo: str, current_version: str) -> Optional[Dict]:
    """
    Checks the GitHub Releases API. `repo` is 'owner/name'. The latest release's
    first .zip asset (preferring one whose name matches the version) is used.
    Returns a normalized dict, or None when unavailable / not newer.
    """
    if not repo or "/" not in repo:
        return None
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(url)
    if not data:
        return None
    version = str(data.get("tag_name", "")).lstrip("vV")
    if not is_newer_version(version, current_version):
        return None

    assets: List[Dict] = data.get("assets") or []
    zip_assets = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    if not zip_assets:
        return None

    asset = zip_assets[0]
    for candidate in zip_assets:
        if version in str(candidate.get("name", "")):
            asset = candidate
            break

    return {
        "version": version,
        "download_url": str(asset.get("browser_download_url", "")),
        "notes": str(data.get("body", "")) or str(data.get("name", "")),
    }


def download_update(download_url: str, dest_path: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Downloads the update zip to dest_path. Returns True on success."""
    try:
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "ZaloPCSyncDrive-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        return os.path.getsize(dest_path) > 0
    except Exception as exc:
        if logger:
            logger.error(f"Update download failed for {download_url}: {exc}")
        return False


def stage_update(zip_path: str, staging_dir: str) -> bool:
    """Extracts the update zip into a staging directory. Returns True on success."""
    try:
        os.makedirs(staging_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging_dir)
        return True
    except Exception as exc:
        if logger:
            logger.error(f"Update staging failed for {zip_path}: {exc}")
        return False


def find_executable(staging_dir: str) -> Optional[str]:
    """Locates ZaloPCSyncDrive.exe inside the staged zip contents."""
    for root, _dirs, files in os.walk(staging_dir):
        for name in files:
            if name.lower() == "zalopcsyncdrive.exe":
                return os.path.join(root, name)
    return None


def create_update_script(staging_dir: str, app_dir: str, script_path: str,
                         relaunch: bool = True) -> bool:
    """
    Writes a .cmd script that waits for the app to exit, replaces the EXE and
    node_bridge, cleans the staging folder, then relaunches the app.
    Returns True on success.
    """
    new_exe = find_executable(staging_dir)
    if not new_exe:
        return False
    target_exe = os.path.join(app_dir, "ZaloPCSyncDrive.exe")
    staging_node = os.path.join(staging_dir, "node_bridge")
    target_node = os.path.join(app_dir, "node_bridge")

    lines = [
        "@echo off",
        "timeout /t 3 /nobreak >nul",
        f'copy /y "{new_exe}" "{target_exe}" >nul',
        "if errorlevel 1 goto :fail",
    ]
    if os.path.isdir(staging_node):
        lines.append(
            f'if exist "{staging_node}" robocopy "{staging_node}" "{target_node}" /E /IS /NFL /NDL /NJH /NJS >nul'
        )
    lines.append(f'rmdir /s /q "{staging_dir}"')
    if relaunch:
        lines.append(f'start "" "{target_exe}"')
    lines.append("exit /b 0")
    lines.append(":fail")
    if relaunch:
        lines.append(f'start "" "{target_exe}"')
    lines.append("exit /b 1")

    try:
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("\n".join(lines))
        return True
    except Exception as exc:
        if logger:
            logger.error(f"Update script creation failed: {exc}")
        return False


def apply_update(zip_path: str, app_dir: str, relaunch: bool = True) -> bool:
    """
    Full update flow: stage the zip, create the swap script, and launch it in a
    detached process. Call this right before quitting the app.
    Returns True when the script was created and launched.
    """
    try:
        update_dir = os.path.join(app_dir, _UPDATE_DIR_NAME)
        staging_dir = os.path.join(update_dir, "staging")
        script_path = os.path.join(update_dir, "update.cmd")

        if not stage_update(zip_path, staging_dir):
            return False
        if not create_update_script(staging_dir, app_dir, script_path, relaunch=relaunch):
            return False

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(["cmd", "/c", script_path], creationflags=creationflags)
        return True
    except Exception as exc:
        if logger:
            logger.error(f"Update apply failed: {exc}")
        return False
