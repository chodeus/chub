"""
Filesystem path safety utilities for CHUB.

Restricts directory listing, creation, and file access to
roots derived from application configuration.
"""

import os
from pathlib import Path
from typing import List

from backend.util.config import ChubConfig


def get_allowed_roots(config: ChubConfig) -> List[Path]:
    """
    Build the list of allowed filesystem roots from configuration.

    Includes:
    - Poster source and destination directories
    - Border replacerr source and destination directories
    - Nohl source directories
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
