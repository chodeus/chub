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
from typing import Any, List, Optional


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


# First char must NOT be '-' (real Drive IDs start alphanumeric), so an ID can't
# be smuggled in as an rclone option even though '-' is otherwise a valid char.
_DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


def _reject_unsafe_id(value: str, field: str) -> None:
    """Strict validator for Google Drive folder/file IDs.

    Drive IDs are always ``[A-Za-z0-9_-]``. Restricting to that charset (on top of
    the list-form subprocess call, which is never shell-interpreted) makes it
    provably impossible for an ID to smuggle an rclone option or any other token
    into the command line.
    """
    if not isinstance(value, str) or not _DRIVE_ID_RE.fullmatch(value):
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


def _upload_auth_args(sync_cfg: Any) -> List[str]:
    """Auth for WRITING to the user's own drive (upload): the OAuth token ONLY.

    Uploading with the user's OAuth token writes as the user, so files land in
    their own Drive folder and are owned by them (this is how PosterFlow does it).
    A service account is intentionally NOT used here: an SA has no storage quota
    and cannot own files in a personal Drive ("Service Accounts do not have
    storage quota"), so the SA upload path always fails. ``[]`` when there is no
    usable OAuth token, so the caller can raise a clear error.
    """
    return _oauth_args(sync_cfg)


def has_upload_token(sync_cfg: Any) -> bool:
    """True when a usable OAuth token is configured for CL2K uploads.

    Lets callers (e.g. the maker UI) warn the user that upload is enabled but
    will fail, without exposing the (redacted) token itself.
    """
    return bool(_upload_auth_args(sync_cfg))


def upload_file(
    local_path: str,
    folder_id: str,
    sync_cfg: Any,
    logger,
) -> None:
    """Copy a single local poster into the Drive folder ``folder_id``.

    Authenticates as the user via the Sync GDrive OAuth token (so the poster
    lands in their own Drive, owned by them). Raises on a missing token or a
    non-zero rclone exit so the caller can record the failure.
    """
    _reject_unsafe_id(folder_id, "gdrive_folder_id")
    auth = _upload_auth_args(sync_cfg)
    if not auth:
        raise RuntimeError(
            "no usable Google Drive OAuth token configured — set a token under "
            "Sync GDrive (a service account cannot own files in a personal Drive)"
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
        raise RuntimeError(f"rclone copy failed: {_rclone_error_detail(result.stderr)}")
    logger.debug(f"uploaded {os.path.basename(local_path)} to drive {folder_id}")


def _rclone_error_detail(stderr: str) -> str:
    """Pull the meaningful cause out of rclone stderr.

    rclone prints a long Drive-API request URL *before* the real error, so a plain
    head-truncation (``[:300]``) hides the cause (the 403/404/auth detail). Prefer
    the explicit Google/OAuth error line; otherwise fall back to the TAIL (where
    rclone's final summary lives), and strip query strings so a redirect/URL with a
    token can't leak into the log.
    """
    err = (stderr or "").strip()
    if not err:
        return "rclone exited non-zero with no stderr"
    # Drop query strings (may contain tokens) before logging anything.
    err = re.sub(r"\?[^\s\"']+", "?…", err)
    m = re.search(
        r"(googleapi: Error \d+:[^\n]+|Error \d{3}[^\n]*|invalid_grant[^\n]*"
        r"|oauth2:[^\n]+|couldn't fetch token[^\n]*|insufficient[^\n]*"
        r"|File not found[^\n]*|not found:[^\n]*)",
        err,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()[:300]
    return err[-300:]  # tail: rclone's final error summary
