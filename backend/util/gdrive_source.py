"""Resolve an asset file's path back to the configured Google Drive that supplied it.

Derived at read time rather than stored on the row: `file` already holds the exact
path and `gdrive_list` is the authority on which drive owns which location, so a
renamed drive reports its current name instead of a stale copy of it.

This is the single owner of the path -> drive question. `poster_renamerr` builds its
style stamp on top of it, and the API read paths use it for provenance, so the
longest-ancestor rule is not spelled out twice.
"""

import os
from typing import Any, Dict, Iterable, Optional


def build_drive_map(gdrive_list: Optional[Iterable[Any]]) -> Dict[str, str]:
    """Map realpath(location) -> the entry's full `name`, for every named entry."""
    out: Dict[str, str] = {}
    for entry in gdrive_list or []:
        loc = (getattr(entry, "location", "") or "").strip()
        name = (getattr(entry, "name", "") or "").strip()
        if loc and name:
            out[os.path.realpath(loc).rstrip("/")] = name
    return out


def resolve_drive_for_path(path: str, drive_map: Dict[str, str]) -> Optional[str]:
    """Value mapped to the longest configured location that is an ancestor of `path`.

    Value-agnostic on purpose: given a name map it yields the drive name, given a
    style map it yields the style. Longest wins so a nested drive beats the parent
    it sits under. None when no configured location covers the path — a plain local
    source_dir, for instance.
    """
    if not drive_map or not path:
        return None
    real = os.path.realpath(path).rstrip("/")
    best_name = None
    best_len = -1
    for loc, name in drive_map.items():
        if (real == loc or real.startswith(loc + "/")) and len(loc) > best_len:
            best_name = name
            best_len = len(loc)
    return best_name


def style_of(drive_name: Optional[str]) -> Optional[str]:
    """Curator family of a drive name: "CL2K Solen" -> "CL2K"."""
    if not drive_name:
        return None
    head = drive_name.split(None, 1)[0]
    return head or None
