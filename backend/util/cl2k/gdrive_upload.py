"""Upload a generated CL2K poster to Google Drive via rclone copy.

Mirrors sync_gdrive's rclone usage (service-account auth, the ``posters`` remote)
but in the upload direction: copy a single local file into a Drive folder. Args
passed to rclone are validated against option-smuggling / null bytes the same way
sync_gdrive does.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from shutil import which
from typing import Any, Dict, List, Optional


def _rclone_path() -> str:
    env = os.getenv("RCLONE_PATH")
    if env:
        if os.path.isfile(env) and os.access(env, os.X_OK):
            return env
        raise FileNotFoundError(f"RCLONE_PATH '{env}' is not an executable file.")
    path = which("rclone")
    if path is None:
        raise FileNotFoundError("rclone not found in PATH; set RCLONE_PATH.")
    return path


def _reject_unsafe(value: str, field: str) -> None:
    if not isinstance(value, str) or "\x00" in value or value.startswith("-"):
        raise ValueError(f"Refusing unsafe {field} value: {value!r}")


def _ensure_remote(rclone: str) -> None:
    """Create the rclone 'posters' remote if missing (idempotent)."""
    subprocess.run(
        [rclone, "config", "create", "posters", "drive", "config_is_local=false"],
        check=False,
        capture_output=True,
        text=True,
    )


def upload_file(
    local_path: str, folder_id: str, sa_location: str, logger
) -> None:
    """Copy a single local poster into the Drive folder ``folder_id``.

    Raises on a non-zero rclone exit so the caller can record the failure.
    """
    _reject_unsafe(folder_id, "gdrive_folder_id")
    rclone = _rclone_path()
    _ensure_remote(rclone)
    cmd = [
        rclone,
        "copy",
        local_path,
        "posters:",
        "--drive-root-folder-id",
        folder_id,
        "--drive-use-trash=false",
        "--no-update-modtime",
        "-v",
    ]
    if sa_location:
        _reject_unsafe(sa_location, "gdrive_sa_location")
        cmd.extend(["--drive-service-account-file", sa_location])

    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rclone copy failed: {result.stderr.strip()[:300]}")
    logger.debug(f"uploaded {os.path.basename(local_path)} to drive {folder_id}")


def _auth_args(sync_cfg: Any) -> List[str]:
    """Build rclone Drive auth flags from the sync_gdrive config.

    Prefers a service-account file (matching :func:`upload_file`); falls back to
    the OAuth client_id/secret/token triple the way ``sync_gdrive.sync_folder``
    does. The .psd source drives are a subset of ``sync_gdrive.gdrive_list``, so
    they authenticate with the same credentials.
    """
    sa = getattr(sync_cfg, "gdrive_sa_location", None)
    if sa:
        _reject_unsafe(sa, "gdrive_sa_location")
        return ["--drive-service-account-file", sa]
    token = getattr(sync_cfg, "token", "") or ""
    if not isinstance(token, str):
        token = json.dumps(
            token.model_dump() if hasattr(token, "model_dump") else dict(token)
        )
    return [
        "--drive-client-id",
        getattr(sync_cfg, "client_id", "") or "",
        "--drive-client-secret",
        getattr(sync_cfg, "client_secret", "") or "",
        "--drive-token",
        token,
    ]


def list_psd(
    sync_cfg: Any, drive_id: str, query: Optional[str] = None
) -> List[Dict[str, str]]:
    """List ``*.psd`` files under the Drive folder ``drive_id`` (recursive).

    When ``query`` is given, only files whose name contains it are returned
    (case-insensitive substring) — essential for the community drives, which hold
    hundreds-to-thousands of PSDs. Returns ``[{"name": basename, "path":
    relative_path}]`` where ``path`` is passed to :func:`fetch_file`.
    """
    _reject_unsafe(drive_id, "drive_id")
    rclone = _rclone_path()
    _ensure_remote(rclone)
    # Strip rclone glob metacharacters so the query is a literal substring, not a
    # pattern (subprocess is list-form, so this is correctness, not shell safety).
    safe = re.sub(r"[*?\[\]{}\\\x00]", "", str(query or "")).strip()
    include = f"*{safe}*.psd" if safe else "*.psd"
    cmd = [
        rclone,
        "lsf",
        "posters:",
        "--drive-root-folder-id",
        drive_id,
        *(["--ignore-case"] if safe else []),
        "--include",
        include,
        "--files-only",
        "-R",
        *_auth_args(sync_cfg),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rclone lsf failed: {result.stderr.strip()[:300]}")
    files = []
    for line in result.stdout.splitlines():
        rel = line.strip()
        if rel:
            files.append({"name": os.path.basename(rel), "path": rel})
    return files


def fetch_file(sync_cfg: Any, drive_id: str, path: str) -> bytes:
    """Download a single file from Drive folder ``drive_id`` and return its bytes."""
    _reject_unsafe(drive_id, "drive_id")
    _reject_unsafe(path, "path")
    rclone = _rclone_path()
    _ensure_remote(rclone)
    cmd = [
        rclone,
        "cat",
        f"posters:{path}",
        "--drive-root-folder-id",
        drive_id,
        *_auth_args(sync_cfg),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", "replace").strip()[:300]
        raise RuntimeError(f"rclone cat failed: {err}")
    return result.stdout
