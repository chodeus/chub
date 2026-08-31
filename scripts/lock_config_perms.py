#!/usr/bin/env python3
"""Restrict the secret-bearing files in CONFIG_DIR. Exits non-zero if any failed."""

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


def main(root: str) -> int:
    # Every open is relative to a NOFOLLOW directory fd: O_NOFOLLOW alone guards
    # only the last component, so a symlinked subdir would redirect the fchmod.
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return 1
    try:
        failed = 0
        for mode, sub, globs in GROUPS:
            if not sub:
                failed |= _lock_dir(root_fd, globs, mode)
                continue
            try:
                sub_fd = os.open(
                    sub, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
                )
            except OSError as exc:
                failed |= exc.errno != errno.ENOENT
                continue
            try:
                failed |= _lock_dir(sub_fd, globs, mode)
            finally:
                os.close(sub_fd)
        return failed
    finally:
        os.close(root_fd)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
