#!/usr/bin/env python3
"""Restrict the secret-bearing files in CONFIG_DIR. Exits non-zero if any failed."""

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


def main(root: str) -> int:
    failed = 0
    for mode, sub, globs in GROUPS:
        base = os.path.join(root, sub) if sub else root
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            if not any(fnmatch.fnmatch(name, pattern) for pattern in globs):
                continue
            # O_NOFOLLOW + fchmod: a symlink swapped in after listdir can't redirect it.
            try:
                fd = os.open(os.path.join(base, name), os.O_RDONLY | os.O_NOFOLLOW)
            except OSError:
                continue
            try:
                if stat.S_ISREG(os.fstat(fd).st_mode):
                    os.fchmod(fd, mode)
            except OSError:
                failed = 1
            finally:
                os.close(fd)
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
