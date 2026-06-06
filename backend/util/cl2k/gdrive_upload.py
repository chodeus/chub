"""Upload a generated CL2K poster to Google Drive via rclone copy.

Mirrors sync_gdrive's rclone usage (service-account auth, the ``posters`` remote)
but in the upload direction: copy a single local file into a Drive folder. Args
passed to rclone are validated against option-smuggling / null bytes the same way
sync_gdrive does.
"""

from __future__ import annotations

import os
import subprocess
from shutil import which


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
