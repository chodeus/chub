"""Put a file at its destination whole: build it under a temp name beside it, then os.replace it in."""

import contextlib
import filecmp
import os
import shutil
import threading
from typing import Callable, Optional


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


def already_in_place(src: str, dest: str, action_type: str) -> bool:
    """True when ``dest`` holds ``src``'s bytes, unless a move onto a link to ``src`` still has ``src`` to remove."""
    if action_type == "move" and not _same_entry(src, dest) and os.path.samefile(src, dest):
        return False
    return filecmp.cmp(src, dest, shallow=False)


def move_into_place(src: str, dest: str) -> Optional[OSError]:
    """Move ``src`` to ``dest``; once it has landed, return why ``src`` could not be deleted, if it could not."""
    if _same_entry(src, dest):
        return None
    if not _same_inode(src, dest):
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
