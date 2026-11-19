"""Name a folder CHUB cannot create files in, or delete a moved source from, with what a user needs to fix the volume."""

import errno
import os
import stat
import tempfile
from typing import Dict, List, Optional, Sequence, TypeVar

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
_KEPT_SOURCE_HINT = (
    "Set File Action to copy, or let CHUB delete files in the source folder "
    "(a read/write mount, owned by PUID/PGID)."
)
# Reads never raise these; a source path named in the error still rules them out.
_DESTINATION_ONLY = frozenset({errno.EROFS, errno.ENOSPC, errno.EDQUOT})


class WriteRefused(Exception):
    """The destination refused a file CHUB was writing."""

    def __init__(self, path: str, err: OSError) -> None:
        super().__init__(f"Cannot write {path}: {err.strerror or err}")
        self.errno = err.errno
        # public_reason walks causes, so the Jobs page names the OS reason ("permission denied", "disk full").
        self.__cause__ = err


_E = TypeVar("_E", OSError, WriteRefused)


def refusal_hint(err: Optional[int]) -> str:
    """What a user can do about a write refused with this errno."""
    return _HINTS.get(err, _DEFAULT_HINT)


def _by_cause(errors: Sequence[_E]) -> List[List[_E]]:
    groups: Dict[Optional[int], List[_E]] = {}
    for err in errors:
        groups.setdefault(err.errno, []).append(err)
    return list(groups.values())


def log_refusals(logger: Logger, refusals: Sequence[WriteRefused], noun: str) -> None:
    """One ERROR per cause, naming the first file it refused and how many."""
    for group in _by_cause(refusals):
        logger.error(
            f"{group[0]}. {refusal_hint(group[0].errno)} "
            f"{len(group)} {noun}(s) failed this way."
        )


def kept_source_text(err: OSError) -> str:
    """What a user sees when a moved file landed but its source could not be deleted."""
    return (
        f"Moved a file but could not delete its source {err.filename}: "
        f"{err.strerror or err}. {_KEPT_SOURCE_HINT}"
    )


def note_kept_source(
    logger: Logger, err: OSError, batch: Optional[List[OSError]]
) -> None:
    """Add ``err`` to ``batch`` for log_kept_sources (logged at DEBUG), or warn now when there is no batch."""
    if batch is None:
        logger.warning(kept_source_text(err))
        return
    logger.debug(kept_source_text(err))
    batch.append(err)


def log_kept_sources(logger: Logger, errors: Sequence[OSError], noun: str) -> None:
    """One WARNING per cause, naming the first source it kept and how many."""
    for group in _by_cause(errors):
        logger.warning(
            f"{kept_source_text(group[0])} {len(group)} {noun}(s) were placed "
            "with their source kept this way."
        )


def _on_the_way(path: str, folder: str) -> bool:
    # The folder, a file in it, or a folder above it that a makedirs was creating.
    return (
        path == folder
        or path.startswith(folder + os.sep)
        or folder.startswith(path + os.sep)
    )


def destination_refused(err: OSError, dest: str) -> bool:
    """True when ``err`` came from ``dest`` or its folder refusing the write, not from the source."""
    folder = os.path.dirname(dest)
    named = [p for p in (err.filename, err.filename2) if p]
    # e.g. a source file CHUB cannot read.
    if named and not any(_on_the_way(p, folder) for p in named):
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
    else:
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
    # A folder may belong to another user (a mount Docker made as root), or refuse files once made.
    refusal = writable_error(path) if check_write else None
    if refusal:
        raise refusal


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
