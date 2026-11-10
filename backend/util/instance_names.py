"""Instance names must differ across service types: lookups by bare name rely on it."""

from collections import defaultdict
from typing import Any, Dict, List, Optional

SERVICE_TYPES = ("radarr", "sonarr", "lidarr", "plex")


def _kinds_by_name(instances: Any) -> Dict[str, List[str]]:
    # Keyed ignoring case: some lookups (poster-cleanarr's) match names that way.
    kinds: Dict[str, List[str]] = defaultdict(list)
    for kind in SERVICE_TYPES:
        for name in getattr(instances, kind, None) or {}:
            if kind not in kinds[name.casefold()]:
                kinds[name.casefold()].append(kind)
    return kinds


def _clash(name: str, kinds: List[str]) -> str:
    labels = [k.capitalize() for k in kinds]
    joined = ", ".join(labels[:-1]) + " and " + labels[-1]
    return (
        f"'{name}' would name {joined} instances; each instance needs its own "
        "name, even across services"
    )


def name_taken(instances: Any, name: str, kind: str) -> Optional[str]:
    """Why a ``kind`` instance may not be called ``name``, or None when it may."""
    kinds = [k for k in _kinds_by_name(instances).get(name.casefold(), []) if k != kind]
    return _clash(name, sorted(kinds + [kind], key=SERVICE_TYPES.index)) if kinds else None


def new_shared_name(before: Any, after: Any) -> Optional[str]:
    """Why ``after`` instances must not be saved: a name newly shared across types, or None."""
    # Only a new clash is refused, so a config that already has one still saves.
    old = _kinds_by_name(before)
    for key, kinds in _kinds_by_name(after).items():
        if len(kinds) > 1 and not set(kinds) <= set(old.get(key, [])):
            shown = next(n for k in kinds for n in getattr(after, k) if n.casefold() == key)
            return _clash(shown, kinds)
    return None
