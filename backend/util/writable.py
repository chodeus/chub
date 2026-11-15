"""Name a folder CHUB cannot create files in, with what a user needs to fix the volume."""

import errno
import os
import stat
import tempfile
from typing import Optional

_OWNER_HINT = "Check the volume's host path, and that the folder's owner matches PUID/PGID."
_HINTS = {
    errno.EACCES: _OWNER_HINT,
    errno.EPERM: _OWNER_HINT,
    errno.EROFS: "The volume is mounted read-only; set its access mode to read/write.",
    errno.ENOSPC: "The disk is full; free some space on it.",
    errno.EDQUOT: "The disk quota is used up; free some space or raise the quota.",
}


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
    hint = _HINTS.get(
        e.errno, "Check the volume's host path, and that its disk or mount is working."
    )
    return (
        f"Cannot create files in {folder}: {e.strerror or e} (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is {owner}). {hint}"
    )
