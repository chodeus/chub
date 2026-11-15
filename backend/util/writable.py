"""Name a folder CHUB cannot create files in, with what a user needs to fix the volume."""

import errno
import os
import stat
import tempfile
from typing import Dict, List, Optional, Sequence

from backend.util.logger import Logger

_OWNER_HINT = "Check the volume's host path, and that the folder's owner matches PUID/PGID."
_HINTS = {
    errno.EACCES: _OWNER_HINT,
    errno.EPERM: _OWNER_HINT,
    errno.EROFS: (
        "The folder is on a read-only mount: set the volume to read/write, "
        "or check the disk if it went read-only on errors."
    ),
    errno.ENOSPC: "The disk is full; free some space on it.",
    errno.EDQUOT: "The disk quota is used up; free some space or raise the quota.",
}
_DEFAULT_HINT = "Check the volume's host path, and that its disk or mount is working."
# Reads never raise these; a source path named in the error still rules them out.
_DESTINATION_ONLY = frozenset({errno.EROFS, errno.ENOSPC, errno.EDQUOT})


class WriteRefused(Exception):
    """The destination refused a file CHUB was writing."""

    def __init__(self, path: str, err: OSError) -> None:
        super().__init__(f"Cannot write {path}: {err.strerror or err}")
        self.errno = err.errno
        # public_reason walks causes, so the Jobs page names the OS reason ("permission denied", "disk full").
        self.__cause__ = err


def refusal_hint(err: Optional[int]) -> str:
    """What a user can do about a write refused with this errno."""
    return _HINTS.get(err, _DEFAULT_HINT)


def log_refusals(logger: Logger, refusals: Sequence[WriteRefused], noun: str) -> None:
    """One ERROR per cause, naming the first file it refused and how many."""
    by_cause: Dict[Optional[int], List[WriteRefused]] = {}
    for refusal in refusals:
        by_cause.setdefault(refusal.errno, []).append(refusal)
    for group in by_cause.values():
        logger.error(
            f"{group[0]}. {refusal_hint(group[0].errno)} "
            f"{len(group)} {noun}(s) failed this way."
        )


def destination_refused(err: OSError, dest: str) -> bool:
    """True when ``err`` came from ``dest`` or its folder refusing the write, not from the source."""
    folder = os.path.dirname(dest)
    named = [p for p in (err.filename, err.filename2) if p]
    # e.g. a cross-device move that copied, then could not delete its read-only source.
    if named and not any(p == folder or p.startswith(folder + os.sep) for p in named):
        return False
    if err.errno in _DESTINATION_ONLY:
        return True
    if err.errno not in (errno.EACCES, errno.EPERM):
        return False
    return dest in named or writable_error(folder) is not None


def ensure_writable_dir(path: str, logger: Logger, check_write: bool = True) -> None:
    """Create ``path`` when missing; raise when CHUB cannot create it, or (check_write) create files in it."""
    if os.path.isdir(path):
        logger.debug(f"Destination directory already exists: {path}")
        # An existing folder may belong to another user (a mount Docker made as root).
        refusal = writable_error(path) if check_write else None
        if refusal:
            raise refusal
        return

    logger.info(f"Creating destination directory: {path}")
    try:
        # exist_ok: a concurrent pass (webhook worker vs the scheduled run) can create it first.
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        # A bare "[Errno 13] Permission denied" never says the volume is not mounted.
        raise FileNotFoundError(
            f"Could not create destination directory: {path} ({e}). "
            "Check the path is correct and its volume is mounted."
        ) from e


def nearest_existing_dir(path: str) -> str:
    """``path``, or its closest ancestor that is a folder."""
    folder = os.path.abspath(path)
    while not os.path.isdir(folder) and os.path.dirname(folder) != folder:
        folder = os.path.dirname(folder)
    return folder


def writable_error(path: str) -> Optional[OSError]:
    """None when CHUB can create files where ``path`` goes; else an OSError naming the folder that refused."""
    folder = nearest_existing_dir(path)
    try:
        # A real create: os.access can misjudge FUSE and network mounts.
        with tempfile.TemporaryFile(dir=folder):
            return None
    except OSError as e:
        return OSError(e.errno, _describe(folder, e))


def _describe(folder: str, e: OSError) -> str:
    try:
        st = os.stat(folder)
        owner = f"owned by {st.st_uid}:{st.st_gid}, {stat.filemode(st.st_mode)}"
    except OSError:
        owner = "of unknown owner"
    hint = refusal_hint(e.errno)
    return (
        f"Cannot create files in {folder}: {e.strerror or e} (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is {owner}). {hint}"
    )
