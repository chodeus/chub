"""Under move to Kometa, where art was placed, so an item whose source another item consumed copies it from there."""

import os
from typing import Dict, List, Optional, Set, Tuple

from backend.util.database.media_cache import MediaCache

Resolved = Tuple[str, Optional[str], Optional[str]]


def _newer(mtime: Optional[float], than: Optional[float]) -> bool:
    return mtime is not None and (than is None or float(mtime) > float(than))


def _recency(placement: Tuple[str, Optional[float]]) -> float:
    return float("-inf") if placement[1] is None else float(placement[1])


def _media_key(media: dict, image_type: str) -> Tuple[str, str]:
    return MediaCache._identity_key(media, media.get("asset_type"), ""), image_type


class AssetMoves:
    """Files placed per media identity, and where each source this run moved went; inert unless active."""

    def __init__(self, active: bool) -> None:
        self.active = active
        self._by_media: Dict[Tuple[str, str], List[Tuple[str, Optional[float]]]] = {}
        self._went: Dict[str, str] = {}
        self._placed: Set[str] = set()

    @classmethod
    def load(
        cls, config, all_media: List[dict], applied_map: dict, image_types: List[str]
    ) -> "AssetMoves":
        """Every placed path match rows record (a Plex row's names no file), active only under move to Kometa."""
        moves = cls(config.apply_method == "kometa" and config.action_type == "move")
        if not moves.active:
            return moves
        for media in all_media:
            if media.get("id") is None:
                continue
            kind = "collection" if media.get("asset_type") == "collection" else "media"
            for image_type in image_types:
                row = applied_map.get((kind, int(media["id"]), image_type)) or {}
                if row.get("applied_path"):
                    pick = row.get("user_confirmed")
                    mtime = None if pick else row.get("source_mtime")
                    moves.add(media, image_type, row["applied_path"], mtime=mtime)
        return moves

    def add(
        self,
        media: dict,
        image_type: str,
        path: str,
        source: Optional[str] = None,
        mtime: Optional[float] = None,
    ) -> None:
        """Record ``path`` as placed for ``media`` from a source of ``mtime`` (None for a pick), moved from ``source`` this run."""
        if not self.active:
            return
        placement = (path, mtime)
        self._by_media.setdefault(_media_key(media, image_type), []).append(placement)
        self._placed.add(path)
        if source:
            self._went[source] = path

    def went(self, source: str) -> Optional[str]:
        """Where this run moved ``source``."""
        return self._went.get(source)

    def sibling(
        self,
        media: dict,
        image_type: str,
        own: Optional[str],
        own_mtime: Optional[float],
    ) -> Optional[Resolved]:
        """The newest file still placed for the same media elsewhere, unless ``own`` came from a source as new."""
        placed = [
            (p, m)
            for p, m in self._by_media.get(_media_key(media, image_type), ())
            if p != own and os.path.isfile(p)
        ]
        if not placed:
            return None
        path, mtime = max(placed, key=_recency)
        if own and not _newer(mtime, own_mtime):
            return None
        return ("local", path, None)

    def lent(self, path: str, own: Optional[str]) -> bool:
        """True for a file placed for another item: copied, never moved."""
        return path != own and path in self._placed
