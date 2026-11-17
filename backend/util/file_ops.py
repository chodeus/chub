"""Put a file at its destination whole (a temp name beside it, then os.replace), and remove the one it supersedes."""

import contextlib
import filecmp
import os
import shutil
import threading
from typing import Any, Callable, Optional

from backend.util.path_safety import resolve_folder


def _into_place(dest: str, make: Callable[[str], None]) -> None:
    # Short per-thread temp beside dest, never dest: a failed op leaves dest whole, a copy
    # chmods only its own file, and "xb" never follows a path already at tmp.
    tmp = os.path.join(
        os.path.dirname(dest), f".chub-tmp-{os.getpid()}-{threading.get_ident()}"
    )
    try:
        make(tmp)
        os.replace(tmp, dest)
    finally:
        # Also after a replace: rename() keeps both names when tmp is a hard link of dest.
        with contextlib.suppress(OSError):
            os.remove(tmp)


def _copy(
    src: str,
    tmp: str,
    copy_meta: Optional[Callable[[str, str], None]] = shutil.copymode,
) -> None:
    with open(src, "rb") as fsrc, open(tmp, "xb") as fdst:
        shutil.copyfileobj(fsrc, fdst)
    if copy_meta:
        copy_meta(src, tmp)


def copy_into_place(src: str, dest: str, keep_mode: bool = True) -> None:
    """Copy ``src`` to ``dest``; without ``keep_mode`` it gets a new file's mode, as shutil.copyfile gives."""
    meta = shutil.copymode if keep_mode else None
    _into_place(dest, lambda tmp: _copy(src, tmp, meta))


def link_into_place(src: str, dest: str) -> None:
    _into_place(dest, lambda tmp: os.link(src, tmp))


def symlink_into_place(src: str, dest: str) -> None:
    # Onto its own path, the file would become a link to itself.
    if _same_entry(src, dest):
        return
    _into_place(dest, lambda tmp: os.symlink(src, tmp))


def _same_inode(src: str, dest: str) -> bool:
    # lstat: a symlink at dest to src is replaced, not mistaken for src.
    try:
        return os.path.samestat(os.lstat(src), os.lstat(dest))
    except OSError:
        return False


def _same_entry(src: str, dest: str) -> bool:
    # dest's own name, not a hard link or a symlink to it: removing src would remove the file.
    try:
        return os.path.basename(src) == os.path.basename(dest) and os.path.samefile(
            os.path.dirname(src) or ".", os.path.dirname(dest) or "."
        )
    except OSError:
        return False


def stale_link(path: str, action_type: str) -> bool:
    """True when ``path`` is a symlink but ``action_type`` places a real file there."""
    return action_type != "symlink" and os.path.islink(path)


def already_in_place(src: str, dest: str, action_type: str) -> bool:
    """True when ``dest`` holds ``src``'s bytes, unless it is a stale link or, for a move, another name for ``src``'s file."""
    if stale_link(dest, action_type):
        return False
    if action_type == "move" and not _same_entry(src, dest) and os.path.samefile(src, dest):
        return False
    return filecmp.cmp(src, dest, shallow=False)


def move_into_place(src: str, dest: str) -> Optional[OSError]:
    """Move ``src`` to ``dest``; once it has landed, return why ``src`` could not be deleted, if it could not."""
    if os.path.islink(src):
        # A link is never moved: dest gets the bytes it points at, which stay where they are.
        _into_place(dest, lambda tmp: _copy(src, tmp, shutil.copystat))
        if _same_entry(src, dest):
            return None
    elif _same_entry(src, dest):
        return None
    elif not _same_inode(src, dest):
        try:
            os.replace(src, dest)
            return None
        except OSError:
            # e.g. EXDEV between two container volumes, or a source folder CHUB cannot change.
            # copystat, as shutil.move's copy2 did: a moved file keeps its times.
            _into_place(dest, lambda tmp: _copy(src, tmp, shutil.copystat))
    try:
        os.remove(src)
    except FileNotFoundError:
        pass  # someone else deleted it mid-move: nothing was kept
    except OSError as e:
        return e
    return None


def _links_to(link: str, path: str) -> bool:
    # A link resolving to path or into its tree (a carry under symlink): that file may be the only copy.
    if not os.path.islink(link):
        return False
    target, root = os.path.realpath(link), resolve_folder(path)
    return target == root or target.startswith(root + os.sep)


def removing_takes(previous: str, current: str) -> bool:
    """Whether removing ``previous`` would also take what ``current`` shows: one entry, a link to or into it, or a case-only twin."""
    if _same_entry(previous, current) or _links_to(current, previous):
        return True
    # A case-insensitive mount (SMB, macOS) sees a case-only rename as one entry.
    return previous.casefold() == current.casefold() and _same_inode(previous, current)


def remove_superseded(
    previous: Optional[str], current: str, root: str, logger: Any, recorded: Callable[[str], bool]
) -> None:
    """Remove the file placed at ``previous`` now that ``current`` replaces it, then its emptied folder; only inside ``root`` and unless ``recorded(previous)``."""
    if not previous or removing_takes(previous, current):
        return
    try:
        real_base = os.path.realpath(root)
        if not resolve_folder(previous).startswith(real_base + os.sep):
            return  # outside the destination: never ours to remove
        # Call after the caller's own row records current: any row still holding previous keeps the file.
        if recorded(previous):
            return
        # A move has already taken it away; its emptied folder still goes.
        if os.path.lexists(previous):
            os.remove(previous)
            logger.debug(f"[CLEANUP] removed superseded asset {previous}")
        parent = os.path.dirname(previous)
        if os.path.realpath(parent) != real_base and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)
            logger.debug(f"[CLEANUP] removed emptied stale folder {parent}")
    except OSError as e:
        logger.warning(f"Could not remove superseded asset {previous}: {e}")
