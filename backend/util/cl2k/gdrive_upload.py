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
import shutil
import subprocess
import tempfile
import threading
import uuid
from collections import defaultdict
from shutil import which
from typing import Any, List, Optional

# One lock per Drive folder. rclone decides "create or replace" by listing the
# destination first, and Drive lets two files share a name — so two uploads
# overlapping in the same folder both see "absent" and both create. Saving twice
# in quick succession is enough (the upload is deferred past the response).
# Single-process assumption: CHUB runs one uvicorn process, so a thread lock
# covers it. Running multiple workers would need a cross-process lock.
_FOLDER_LOCKS_GUARD = threading.Lock()
_FOLDER_LOCKS: "defaultdict[str, threading.Lock]" = defaultdict(threading.Lock)


def _folder_lock(folder_id: str) -> threading.Lock:
    with _FOLDER_LOCKS_GUARD:
        return _FOLDER_LOCKS[folder_id]


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
    client_id = getattr(sync_cfg, "client_id", "") or ""
    client_secret = getattr(sync_cfg, "client_secret", "") or ""
    # Config-sourced, so they reach the argv the same way gdrive_sa_location does
    # — and a value starting with "-" would be read by rclone as an option, not
    # data. Real Google credentials never do (ids are numeric-led, secrets are
    # GOCSPX-…, the token is JSON), so this rejects only malformed input.
    _reject_unsafe(client_id, "gdrive_client_id")
    _reject_unsafe(client_secret, "gdrive_client_secret")
    _reject_unsafe(token, "gdrive_token")
    return [
        "--drive-client-id",
        client_id,
        "--drive-client-secret",
        client_secret,
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
    _reject_unsafe(local_path, "local_path")
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
    # Serialised per folder: see _FOLDER_LOCKS. rclone replaces a same-named file
    # correctly on its own — it only duplicates when two runs overlap.
    with _folder_lock(folder_id):
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"rclone copy failed: {_rclone_error_detail(result.stderr)}"
            )
        _reap_duplicates(os.path.basename(local_path), folder_id, sync_cfg, logger)
    logger.debug(f"uploaded {os.path.basename(local_path)} to drive {folder_id}")


def _reap_duplicates(name: str, folder_id: str, sync_cfg: Any, logger) -> None:
    """Collapse same-named copies of ``name``, keeping the newest — ours.

    Repairs duplicates the lock can't prevent: ones already in the folder, or
    written by another CHUB instance. Costs one listing per upload and only
    deletes when a duplicate of the file we just wrote actually exists, so the
    normal path never runs a destructive command. Never raises: the upload
    succeeded, and failing to tidy up must not report it as failed.
    """
    try:
        names = list_files(folder_id, sync_cfg, logger, strict=True)
        if sum(1 for n in names if n == name) < 2:
            return
        logger.warning(
            f"CL2K drive {folder_id}: {name} exists more than once — keeping the newest"
        )
        auth = _upload_auth_args(sync_cfg)
        rclone = _rclone_path()
        result = subprocess.run(
            [
                rclone,
                "dedupe",
                "--dedupe-mode",
                "newest",
                "posters:",
                "--drive-root-folder-id",
                folder_id,
                "--drive-use-trash=false",
                *auth,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                f"CL2K drive dedupe failed: {_rclone_error_detail(result.stderr)}"
            )
    except Exception as exc:
        logger.warning(f"CL2K drive duplicate check failed for {name}: {exc}")


def move_file(
    old_name: str,
    new_name: str,
    folder_id: str,
    sync_cfg: Any,
    logger,
) -> None:
    """Rename a file in the Drive folder ``folder_id`` (``old_name`` -> ``new_name``).

    A server-side rename via ``rclone moveto``, authenticated as the user with the
    Sync GDrive OAuth token (the same write path as :func:`upload_file`) so it can
    write to the user's own Drive. Both names are relative to ``folder_id`` (the
    rclone root). Used by the poster healer to rewrite a poster's embedded id /
    title on the user's Drive. Raises on a missing token or non-zero rclone exit.
    """
    _reject_unsafe_id(folder_id, "gdrive_folder_id")
    _reject_unsafe(old_name, "gdrive_old_name")
    _reject_unsafe(new_name, "gdrive_new_name")
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
        "moveto",
        f"posters:{old_name}",
        f"posters:{new_name}",
        "--drive-root-folder-id",
        folder_id,
        "--drive-use-trash=false",
        "--no-update-modtime",
        "-v",
        *auth,
    ]
    # Same lock as upload_file: this is the folder's other writer (the healer
    # renames while the maker uploads), and a rename onto a name an upload is
    # creating duplicates it just as readily.
    with _folder_lock(folder_id):
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"rclone moveto failed: {_rclone_error_detail(result.stderr)}"
        )
    logger.debug(f"renamed {old_name} -> {new_name} in drive {folder_id}")


def list_files(folder_id: str, sync_cfg: Any, logger, strict: bool = False) -> List[str]:
    """List the file names (top level, files only) in the Drive folder
    ``folder_id`` via ``rclone lsf``.

    Used by the poster healer's live-Drive source so it can heal posters saved
    straight to Drive (a Drive-only save is never recorded in poster_cache).
    Authenticated with the Sync GDrive OAuth token, like upload_file/move_file.
    Returns [] (logging a warning) on a missing token or any rclone failure — a
    Drive-listing problem must not abort a run that may still have local posters
    to heal. Names are returned relative to ``folder_id`` (the rclone root), the
    same form move_file expects.

    ``strict=True`` RAISES instead of returning [] — required by any caller that
    reads an empty listing as "the name is free". Returning [] on failure would
    make a transient listing error look like "no collision" and let a destructive
    rename proceed.
    """
    _reject_unsafe_id(folder_id, "gdrive_folder_id")
    auth = _upload_auth_args(sync_cfg)
    if not auth:
        if strict:
            raise RuntimeError(
                "no usable Google Drive OAuth token configured — cannot list "
                "the folder to check for a name collision"
            )
        logger.warning(
            "poster_self_heal: no Google Drive OAuth token — skipping live Drive "
            "listing (set one under Sync GDrive)"
        )
        return []
    rclone = _rclone_path()
    _ensure_remote(rclone)
    cmd = [
        rclone,
        "lsf",
        "posters:",
        "--drive-root-folder-id",
        folder_id,
        "--files-only",
        *auth,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = _rclone_error_detail(result.stderr)
        if strict:
            raise RuntimeError(f"rclone lsf failed: {detail}")
        logger.warning(f"poster_self_heal: rclone lsf failed: {detail}")
        return []
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


# image_type -> the Drive subfolder the community artwork drives use for it. A
# FIXED map, never user input, so these never widen the rclone argument surface.
TYPE_SUBFOLDERS = {
    "logo": "logos",
    "background": "backgrounds",
    "squareart": "squareart",
}


def ensure_type_subfolders(folder_id: str, sync_cfg: Any, logger) -> List[dict]:
    """Create (or find) ``logos``/``backgrounds``/``squareart`` under ``folder_id``.

    Returns one ``{image_type, name, folder_id, created}`` per subfolder so the
    caller can store real child ids — the upload path still addresses exactly one
    Drive folder per destination. Raises on a missing token or rclone failure.
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

    def _dir_ids() -> dict:
        result = subprocess.run(
            [
                rclone,
                "lsjson",
                "posters:",
                "--drive-root-folder-id",
                folder_id,
                "--dirs-only",
                *auth,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"rclone lsjson failed: {_rclone_error_detail(result.stderr)}"
            )
        # Keep only usable ids: a blank/absent/non-string ID must NOT register the
        # name, or the completeness check below passes and we hand back a routed
        # row whose folder_id is empty — which _drive_targets skips silently, so
        # that art type would just stop uploading with no error anywhere.
        return {
            d["Name"]: d["ID"]
            for d in json.loads(result.stdout or "[]")
            if isinstance(d.get("ID"), str) and d["ID"].strip()
        }

    existing = _dir_ids()
    made = []
    for name in TYPE_SUBFOLDERS.values():
        if name in existing:
            continue
        result = subprocess.run(
            [rclone, "mkdir", f"posters:{name}", "--drive-root-folder-id", folder_id, *auth],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"rclone mkdir '{name}' failed: {_rclone_error_detail(result.stderr)}"
            )
        made.append(name)

    # Re-list once so newly created folders come back with their real ids.
    ids = _dir_ids() if made else existing
    missing = [n for n in TYPE_SUBFOLDERS.values() if n not in ids]
    if missing:
        raise RuntimeError(f"Drive did not return an id for: {', '.join(missing)}")
    logger.info(
        f"cl2k: type subfolders under {folder_id} — created {made or 'none'}, "
        f"reused {[n for n in TYPE_SUBFOLDERS.values() if n not in made]}"
    )
    return [
        {
            "image_type": image_type,
            "name": name,
            "folder_id": ids[name],
            "created": name in made,
        }
        for image_type, name in TYPE_SUBFOLDERS.items()
    ]


def delete_file(name: str, folder_id: str, sync_cfg: Any, logger) -> None:
    """Delete the single file ``name`` from Drive folder ``folder_id`` via
    ``rclone deletefile``. ``name`` is relative to ``folder_id`` (the rclone
    root). Authenticated with the Sync GDrive OAuth token. Raises on a missing
    token or non-zero rclone exit."""
    _reject_unsafe_id(folder_id, "gdrive_folder_id")
    _reject_unsafe(name, "gdrive_name")
    auth = _upload_auth_args(sync_cfg)
    if not auth:
        raise RuntimeError("no usable Google Drive OAuth token configured")
    rclone = _rclone_path()
    _ensure_remote(rclone)
    cmd = [
        rclone,
        "deletefile",
        f"posters:{name}",
        "--drive-root-folder-id",
        folder_id,
        "--drive-use-trash=false",
        *auth,
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"rclone deletefile failed: {_rclone_error_detail(result.stderr)}"
        )


def test_drive_access(folder_id: str, sync_cfg: Any, logger) -> str:
    """Verify CHUB can UPLOAD to Drive folder ``folder_id``.

    Copies a tiny marker file into the folder (proving write access as the
    user), then deletes it. Raises ``RuntimeError`` with a clear reason on any
    failure (no token / bad folder id / auth / rclone error). Returns a short
    success detail string. The marker is a ``.txt`` (never a poster image type)
    so a concurrent sync would ignore it even in the rare window before delete.
    """
    _reject_unsafe_id(folder_id, "gdrive_folder_id")
    if not has_upload_token(sync_cfg):
        raise RuntimeError(
            "no usable Google Drive OAuth token configured — set a token under "
            "Sync GDrive (a service account cannot own files in a personal Drive)"
        )
    marker = f".chub_upload_test_{uuid.uuid4().hex}.txt"
    tmpdir = tempfile.mkdtemp(prefix="cl2k_test_")
    local = os.path.join(tmpdir, marker)
    try:
        with open(local, "w", encoding="utf-8") as fh:
            fh.write("CHUB upload connectivity test — safe to delete.\n")
        upload_file(local, folder_id, sync_cfg, logger)
        try:
            delete_file(marker, folder_id, sync_cfg, logger)
            return "Uploaded and removed a test file — upload works."
        except Exception as exc:
            # Write already succeeded (the real thing we're testing); only the
            # cleanup failed. Report success but flag the leftover.
            logger.warning(f"cl2k test-drive: cleanup of {marker} failed: {exc}")
            return (
                "Upload works, but the temporary test file could not be removed "
                f"({marker}) — you may want to delete it manually."
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
