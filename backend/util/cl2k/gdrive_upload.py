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


def _sa_args(sa_location: Optional[str]) -> List[str]:
    if not sa_location:
        return []
    _reject_unsafe(sa_location, "gdrive_sa_location")
    return ["--drive-service-account-file", sa_location]


def _oauth_args(sync_cfg: Any) -> List[str]:
    """rclone OAuth flags from the sync_gdrive config; [] when there is no
    *usable* token, so callers fall back to the service account.

    sync_gdrive stores a placeholder token (often the literal ``"{}"``) when only
    a service account is configured. That is truthy but NOT a real OAuth token,
    so we require it to actually carry an access/refresh token before taking the
    OAuth path — otherwise an SA-only setup would try (and fail) bogus OAuth
    instead of using its service account.
    """
    token = getattr(sync_cfg, "token", "")
    if token and not isinstance(token, str):
        token = json.dumps(
            token.model_dump() if hasattr(token, "model_dump") else dict(token)
        )
    token = (token or "").strip()
    if "access_token" not in token and "refresh_token" not in token:
        return []
    return [
        "--drive-client-id",
        getattr(sync_cfg, "client_id", "") or "",
        "--drive-client-secret",
        getattr(sync_cfg, "client_secret", "") or "",
        "--drive-token",
        token,
    ]


def _auth_args(sync_cfg: Any) -> List[str]:
    """Auth for READING shared drives (browse): service account first, then OAuth.

    The community .psd drives are shared with the service account, so SA is the
    natural credential; OAuth is the fallback.
    """
    sa = _sa_args(getattr(sync_cfg, "gdrive_sa_location", None))
    return sa or _oauth_args(sync_cfg)


def _upload_auth_args(sync_cfg: Any, sa_override: Optional[str] = None) -> List[str]:
    """Auth for WRITING to the user's own drive (upload): OAuth first, then SA.

    Uploading with the user's OAuth token writes as the user, so files land in
    their own Drive folder and are owned by them — no service-account sharing
    needed (this is how PosterFlow does it). An explicit ``sa_override``
    (cl2k_maker.gdrive_sa_location) takes precedence for users who deliberately
    upload through a service account; the sync_gdrive SA is the last resort.
    """
    if sa_override:
        return _sa_args(sa_override)
    return _oauth_args(sync_cfg) or _sa_args(getattr(sync_cfg, "gdrive_sa_location", None))


def upload_file(
    local_path: str,
    folder_id: str,
    sync_cfg: Any,
    logger,
    sa_override: Optional[str] = None,
) -> None:
    """Copy a single local poster into the Drive folder ``folder_id``.

    Authenticates as the user via OAuth by default (so the poster lands in their
    own Drive, owned by them); falls back to a service account. Raises on a
    non-zero rclone exit so the caller can record the failure.
    """
    _reject_unsafe(folder_id, "gdrive_folder_id")
    auth = _upload_auth_args(sync_cfg, sa_override)
    if not auth:
        raise RuntimeError(
            "no Google Drive credentials configured "
            "(set Sync GDrive OAuth token or a service account)"
        )
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
        *auth,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"rclone copy failed: {result.stderr.strip()[:300]}")
    logger.debug(f"uploaded {os.path.basename(local_path)} to drive {folder_id}")


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
