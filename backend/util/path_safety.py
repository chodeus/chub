"""
Filesystem path safety utilities for CHUB.

Restricts directory listing, creation, and file access to
roots derived from application configuration.
"""

import os
from pathlib import Path
from typing import List, Optional

from backend.util.config import ChubConfig


def get_allowed_roots(config: ChubConfig) -> List[Path]:
    """
    Build the list of allowed filesystem roots from configuration.

    Includes:
    - Poster source and destination directories
    - Border replacerr source and destination directories
    - Nohl source directories
    - Jduparr source directories and hash database location
    - GDrive source locations
    - The app config directory itself
    """
    roots: List[str] = []

    # Poster renamerr
    pr = config.poster_renamerr
    roots.extend(pr.source_dirs)
    if pr.destination_dir:
        roots.append(pr.destination_dir)

    # Border replacerr
    br = config.border_replacerr
    roots.extend(br.source_dirs)
    if br.destination_dir:
        roots.append(br.destination_dir)

    # Nohl source dirs
    for src in config.nohl.source_dirs:
        if isinstance(src, str):
            roots.append(src)
        elif hasattr(src, "path"):
            roots.append(src.path)

    # Jduparr source dirs and optional hash database location
    roots.extend(config.jduparr.source_dirs)
    if config.jduparr.hash_database:
        roots.append(str(Path(config.jduparr.hash_database).expanduser().parent))

    # GDrive locations
    for entry in config.sync_gdrive.gdrive_list:
        if entry.location:
            roots.append(entry.location)
    if config.sync_gdrive.gdrive_sa_location:
        roots.append(config.sync_gdrive.gdrive_sa_location)

    # App config directory (so users can browse config location)
    config_dir = os.environ.get("CONFIG_DIR") or str(
        Path(__file__).parent.parent.parent / "config"
    )
    roots.append(config_dir)

    # Auto-discover bind-mounted host volumes (Linux containers). On Unraid
    # / docker, the user's template typically binds paths like /kometa,
    # /media, /data, /plex into the container. Surface them so the picker
    # works for fresh setups before any config field has been populated.
    roots.extend(str(p) for p in _discover_container_mounts())

    # Resolve all and deduplicate
    resolved = []
    for r in roots:
        if not r:
            continue
        try:
            p = Path(r).expanduser().resolve()
            if p.exists():
                resolved.append(p)
        except (ValueError, OSError):
            continue

    return list(set(resolved))


# Pseudo / system filesystems we never want to expose via the picker.
_PSEUDO_FS_TYPES = frozenset(
    {
        "proc",
        "sysfs",
        "cgroup",
        "cgroup2",
        "devpts",
        "tmpfs",
        "mqueue",
        "pstore",
        "bpf",
        "tracefs",
        "securityfs",
        "debugfs",
        "fusectl",
        "configfs",
        "autofs",
        "nsfs",
        "binfmt_misc",
        "hugetlbfs",
        "ramfs",
        "rpc_pipefs",
        "overlay",
        "squashfs",
    }
)

# Mount points (or prefixes) that are part of the container OS, not user data.
_SYSTEM_MOUNT_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/etc",
    "/usr",
    "/var",
    "/lib",
    "/lib64",
    "/sbin",
    "/bin",
    "/boot",
    "/tmp",
)


def _discover_container_mounts(
    mountinfo_path: str = "/proc/self/mountinfo",
) -> List[Path]:
    """
    Read mountinfo and return user-data bind mounts.

    Filters out pseudo-filesystems (proc, sysfs, tmpfs, overlay, etc.)
    and OS-level mount points (/proc, /sys, /dev, /usr, /var, ...). What
    remains is the set of paths the user explicitly bound into the
    container — exactly what the directory picker should expose.

    Returns an empty list on non-Linux hosts or if mountinfo is unreadable.
    The path arg is exposed only so tests can inject a fixture file.
    """
    try:
        with open(mountinfo_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, IOError):
        return []

    discovered: List[Path] = []
    seen: set = set()
    for line in lines:
        # mountinfo format:
        #   <id> <parent> <maj:min> <root> <mount_point> <opts> [<tags>...] - <fs_type> <source> <super_opts>
        fields = line.rstrip("\n").split(" ")
        if len(fields) < 5:
            continue
        mount_point = fields[4]

        try:
            dash_idx = fields.index("-")
        except ValueError:
            continue
        if dash_idx + 1 >= len(fields):
            continue
        fs_type = fields[dash_idx + 1]

        if fs_type in _PSEUDO_FS_TYPES:
            continue
        if mount_point == "/" or mount_point in seen:
            continue
        if any(
            mount_point == p or mount_point.startswith(p + "/")
            for p in _SYSTEM_MOUNT_PREFIXES
        ):
            continue

        seen.add(mount_point)
        discovered.append(Path(mount_point))

    return discovered


def get_browse_roots(config: ChubConfig) -> List[Path]:
    """
    Top-level directory roots suitable for the UI directory picker.

    Built on top of ``get_allowed_roots`` but:
    - drops file paths (e.g. the gdrive service-account .json), since
      the picker only navigates directories;
    - collapses each path to its outermost allowed ancestor, so a
      configured ``/kometa/posters/MM2K/Mario`` doesn't show up as a
      separate root when ``/kometa`` is already mounted.

    The full unfiltered list is still used by ``is_path_allowed`` for
    write-permission checks; this is just what gets surfaced to the user.
    """
    all_roots = get_allowed_roots(config)
    dir_roots = [p for p in all_roots if p.is_dir()]
    # Shortest paths first so we add ancestors before descendants.
    dir_roots.sort(key=lambda p: len(p.parts))
    top_level: List[Path] = []
    for r in dir_roots:
        # Skip if this path is already covered by a shorter root.
        if any(top in r.parents for top in top_level):
            continue
        top_level.append(r)
    return top_level


def is_path_allowed(path: str, config: ChubConfig) -> bool:
    """
    Check whether *path* falls under one of the allowed roots.
    Returns True if the resolved path is inside any allowed root.

    The path is resolved to an absolute path and then checked against
    each allowed root using Path.relative_to(), which is safe against
    traversal attacks (symlinks, .., etc.) because resolve() normalizes.
    """
    if not path or not isinstance(path, str):
        return False
    # Reject null bytes (path injection vector)
    if "\x00" in path:
        return False
    try:
        target = Path(path).expanduser().resolve()  # noqa: S108 — validated below
    except (ValueError, OSError):
        return False

    for root in get_allowed_roots(config):
        try:
            target.relative_to(root)
            return True
        except ValueError:
            continue

    return False


def resolve_confined(path: str, config: ChubConfig) -> Optional[Path]:
    """
    Resolve *path* and return it only if the RESOLVED path is inside an allowed root.

    Returns None when the path is unusable or escapes the roots — so callers
    fail closed with a single `is None` check instead of hand-rolling
    resolve-then-authorize (a symlink inside a root must not serve its target
    outside the roots).

    This is the one canonical confinement call for anything that serves a
    user-supplied path. Keeping the pattern here gives CodeQL's py/path-injection
    alerts a single stable anchor to dismiss against, instead of re-minting on
    every edit to each individual path-serving handler.
    """
    if not path or not isinstance(path, str):
        return None
    try:
        resolved = Path(path).expanduser().resolve()
    except (ValueError, OSError):
        return None
    return resolved if is_path_allowed(str(resolved), config) else None
