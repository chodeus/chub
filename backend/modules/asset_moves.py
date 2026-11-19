"""Under move to Kometa, where art was placed, for items whose source is gone."""

import os
from typing import Callable, Dict, List, Optional, Set, Tuple

from backend.util.database.media_cache import MediaCache

Resolved = Tuple[str, Optional[str], Optional[str]]


def _newer(mtime: Optional[float], than: Optional[float]) -> bool:
    return mtime is not None and (than is None or float(mtime) > float(than))


def _recency(mtime: Optional[float]) -> float:
    return float("-inf") if mtime is None else float(mtime)


def _media_key(media: dict, image_type: str) -> Tuple[str, str]:
    return MediaCache.media_identity(media), image_type


class AssetMoves:
    """Placed files per media, and where this run moved each source."""

    def __init__(self, active: bool, picked: Callable[[str], bool]) -> None:
        self.active = active
        self._picked = picked
        self._by_media: Dict[Tuple[str, str], List[str]] = {}
        self._went: Dict[str, str] = {}
        self._placed: Dict[str, Optional[float]] = {}
        self._written: Dict[str, Tuple[str, float]] = {}
        self._picks: Set[str] = set()
        self._rows: Dict[Tuple[str, str], List[dict]] = {}
        self._held: Dict[Tuple[str, str], bool] = {}

    @classmethod
    def load(
        cls,
        config,
        all_media: List[dict],
        applied_map: dict,
        image_types: List[str],
        picked: Callable[[str], bool],
    ) -> "AssetMoves":
        """Every applied_path the rows record; active only under move to Kometa."""
        active = config.apply_method == "kometa" and config.action_type == "move"
        moves = cls(active, picked)
        if not moves.active:
            return moves
        for media in all_media:
            if media.get("id") is None:
                continue
            kind = "collection" if media.get("asset_type") == "collection" else "media"
            for image_type in image_types:
                row = applied_map.get((kind, int(media["id"]), image_type)) or {}
                if row.get("applied_path"):
                    moves._record(media, image_type, row)
        return moves

    def _record(self, media: dict, image_type: str, row: dict) -> None:
        """One row's placement; a shared path takes the time of the row written last."""
        path, mtime = row["applied_path"], row.get("source_mtime")
        rank = (row.get("matched_at") or "", _recency(mtime))
        if path in self._written and self._written[path] >= rank:
            mtime = self._placed[path]
        else:
            self._written[path] = rank
        pick = bool(row.get("user_confirmed"))
        self.add(media, image_type, path, mtime=mtime, pick=pick)
        if not pick:
            self._rows.setdefault(_media_key(media, image_type), []).append(row)

    def _on_disk(self, row: dict) -> bool:
        """True when the row's recorded source is a file, not one placed for an item."""
        source = row.get("matched_file")
        return bool(source) and source not in self._placed and os.path.isfile(source)

    def held(self, media: dict, image_type: str) -> bool:
        """True while auto-placed art stands and none of its recorded sources does."""
        key = _media_key(media, image_type)
        if key not in self._held:  # once per media per run, from the rows as loaded
            rows = self._rows.get(key, [])
            self._held[key] = not any(map(self._on_disk, rows)) and any(
                os.path.isfile(r["applied_path"]) for r in rows
            )
        return self._held[key]

    def add(
        self,
        media: dict,
        image_type: str,
        path: str,
        source: Optional[str] = None,
        mtime: Optional[float] = None,
        pick: bool = False,
    ) -> None:
        """Record ``path`` placed from ``source``; sibling() never offers a pick."""
        if not self.active:
            return
        paths = self._by_media.setdefault(_media_key(media, image_type), [])
        if path not in paths:
            paths.append(path)
        self._placed[path] = mtime  # on load, _record passes its last-written row's
        if pick:
            self._picks.add(path)
        if source:
            self._went[source] = path

    def went(self, source: str) -> Optional[str]:
        """Where this run moved ``source``, unless that file is gone or a pick."""
        path = self._went.get(source)
        if path is None or path in self._picks or not os.path.isfile(path):
            return None
        if self._picked(path):  # picked in the UI since it was placed
            self._picks.add(path)
            return None
        return path

    def sibling(
        self,
        media: dict,
        image_type: str,
        own: Optional[str],
        own_mtime: Optional[float],
    ) -> Optional[Resolved]:
        """The newest non-pick file placed for this media, unless own's is as new."""
        placed = [
            p
            for p in self._by_media.get(_media_key(media, image_type), ())
            # isfile also drops a Plex row's library names.
            if p not in self._picks and os.path.isfile(p)
        ]
        if not placed:
            return None
        path = max(placed, key=lambda p: _recency(self._placed[p]))
        # Another row's write may have changed the file at own's path.
        own_mtime = self._placed.get(own, own_mtime) if own else own_mtime
        if own and not _newer(self._placed[path], own_mtime):
            return None
        if self._picked(path):  # picked in the UI since load
            self._picks.add(path)
            return self.sibling(media, image_type, own, own_mtime)
        return ("local", path, None)

    def lent(self, path: str, own: Optional[str]) -> bool:
        """True for a file placed for another item: copied, never moved."""
        return path != own and path in self._placed

    def source_mtime(self, path: str) -> Optional[float]:
        """When ``path``'s source changed; for a placed file, as recorded."""
        if path in self._placed:  # lent, or own carried: either may be a fresh copy
            return self._placed[path]
        try:
            return os.stat(path).st_mtime
        except OSError:
            return None
