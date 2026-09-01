#!/usr/bin/env python3
"""Fix ownership and lock secret modes under CONFIG_DIR without following symlinks."""

import errno
import fnmatch
import os
import stat
import sys

# (mode, subdirectory of CONFIG_DIR, filename globs)
GROUPS = [
    (0o600, "", ("config.yml", "config.yml.legacy-*", "*.json")),
    (0o660, "", ("chub.db",)),
    (0o660, "rclone", ("rclone.conf",)),
]

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _chown_tree(root_fd: int, uid: int, gid: int) -> None:
    """Chown entries whose owner differs, descending only through NOFOLLOW dir fds."""
    stack = [root_fd]
    opened = []
    try:
        while stack:
            dir_fd = stack.pop()
            for name in os.listdir(dir_fd):
                try:
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                except OSError:
                    continue
                if info.st_uid != uid or info.st_gid != gid:
                    # Foreign uids on a network mount fail here and that is benign;
                    # the write probe in start.sh is what fails closed.
                    try:
                        os.chown(name, uid, gid, dir_fd=dir_fd, follow_symlinks=False)
                    except OSError:
                        pass
                if stat.S_ISDIR(info.st_mode):
                    try:
                        sub = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
                    except OSError:
                        continue
                    opened.append(sub)
                    stack.append(sub)
    finally:
        for fd in opened:
            os.close(fd)


def _lock_dir(dir_fd: int, globs: tuple, mode: int) -> int:
    failed = 0
    for name in os.listdir(dir_fd):
        if not any(fnmatch.fnmatch(name, pattern) for pattern in globs):
            continue
        # O_NONBLOCK so a FIFO planted under a matching name can't hang the boot.
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd
            )
        except OSError as exc:
            # Vanished between listdir and open; anything else is worth reporting.
            failed |= exc.errno != errno.ENOENT
            continue
        try:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                os.fchmod(fd, mode)
        except OSError:
            failed = 1
        finally:
            os.close(fd)
    return failed


def _lock_tree(root_fd: int) -> int:
    failed = 0
    for mode, sub, globs in GROUPS:
        if not sub:
            failed |= _lock_dir(root_fd, globs, mode)
            continue
        try:
            sub_fd = os.open(sub, _DIR_FLAGS, dir_fd=root_fd)
        except OSError as exc:
            failed |= exc.errno != errno.ENOENT
            continue
        try:
            failed |= _lock_dir(sub_fd, globs, mode)
        finally:
            os.close(sub_fd)
    return failed


def main(argv: list) -> int:
    # Every open hangs off a NOFOLLOW directory fd: a path-based chown or chmod
    # follows an intermediate directory swapped for a symlink after validation.
    mode, root = argv[0], argv[1]
    try:
        root_fd = os.open(root, _DIR_FLAGS)
    except OSError:
        return 1
    try:
        if mode == "chown":
            uid, gid = int(argv[2]), int(argv[3])
            if os.stat(root_fd).st_uid != uid or os.stat(root_fd).st_gid != gid:
                try:
                    os.fchown(root_fd, uid, gid)
                except OSError:
                    pass
            _chown_tree(root_fd, uid, gid)
            return 0
        return _lock_tree(root_fd)
    finally:
        os.close(root_fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
