"""Put a file at its destination whole: build it under a temp name beside it, then os.replace it in."""

import contextlib
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
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise


def _copy(src: str, tmp: str) -> None:
    with open(src, "rb") as fsrc, open(tmp, "xb") as fdst:
        shutil.copyfileobj(fsrc, fdst)
    shutil.copymode(src, tmp)


def copy_into_place(src: str, dest: str) -> None:
    _into_place(dest, lambda tmp: _copy(src, tmp))


def link_into_place(src: str, dest: str) -> None:
    _into_place(dest, lambda tmp: os.link(src, tmp))


def symlink_into_place(src: str, dest: str) -> None:
    _into_place(dest, lambda tmp: os.symlink(src, tmp))


def move_into_place(src: str, dest: str) -> Optional[OSError]:
    """Move ``src`` to ``dest``; once it has landed, return why ``src`` could not be deleted, if it could not."""
    try:
        os.replace(src, dest)
        return None
    except OSError:
        # e.g. EXDEV between two container volumes, or a source folder CHUB cannot change.
        copy_into_place(src, dest)
    try:
        os.remove(src)
    except FileNotFoundError:
        pass
    except OSError as e:
        return e
    return None
