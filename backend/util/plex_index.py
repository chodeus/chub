"""Shared in-memory index over CHUB's ``plex_media_cache`` rows.

Both the poster uploader and the asset-renamerr "plex" apply path need to map a
matched media/collection row to the Plex library entries that should receive
artwork. Resolving that with a live ``section.search(title, year)`` per item —
per art type, per library — is slow and noisy (it re-searches the same item for
logo, background, square art, and every season, and searches wrong-type
libraries that can never hold it).

``PlexMediaIndex`` builds the lookup ONCE from the already-synced
``plex_media_cache`` snapshot, keyed guid-first (tmdb/imdb/tvdb) with a
normalized-title fallback, split by media type so a movie is never looked up
against a show library. Each key maps to a *list* of entries because the same
title can live in more than one enabled library on a single server (e.g. a
"Movies" and a separate "Movies 4K" library) — every copy must receive the art.

This module is the single source of truth for that keying; callers that need
fresher data than the cache provides layer a lazy live fallback on top (see
asset_renamerr) — the index is the fast path, not the only path.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from backend.util.normalization import normalize_titles

# Priority order of match keys per media type (highest-confidence first). Guids
# beat titles; tvdb leads for shows (Sonarr's native id), tmdb for movies.
MOVIE_PRIORITY_KEYS = ["tmdb", "imdb", "title"]
SHOW_PRIORITY_KEYS = ["tvdb", "tmdb", "imdb", "title"]
SEASON_PRIORITY_KEYS = ["tvdb", "tmdb", "imdb", "title"]
COLLECTION_PRIORITY_KEYS = ["title"]


def _coerce_guids(value: Any) -> Dict[str, Any]:
    """A plex_media_cache row's ``guids`` may be a dict or a JSON string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


class PlexMediaIndex:
    """Type-separated, guid-first index over plex_media_cache rows.

    Build once per instance snapshot, then call :meth:`resolve` per media row.
    """

    def __init__(self, media_cache: List[Dict]) -> None:
        self.movies: Dict[str, List[Dict]] = {}
        self.shows: Dict[str, List[Dict]] = {}
        self.seasons: Dict[str, List[Dict]] = {}
        self.collections: Dict[str, List[Dict]] = {}
        self._build(media_cache or [])

    # ----- build ----------------------------------------------------------

    @staticmethod
    def _add(index: Dict[str, List[Dict]], key: str, entry: Dict) -> None:
        index.setdefault(key, []).append(entry)

    def _build(self, media_cache: List[Dict]) -> None:
        for entry in media_cache:
            try:
                typ = entry.get("asset_type")
                norm_title = entry.get("normalized_title")
                guids = _coerce_guids(entry.get("guids", {}))

                if typ == "movie":
                    if norm_title:
                        self._add(self.movies, f"title:{norm_title}", entry)
                    if guids.get("tmdb"):
                        self._add(self.movies, f"tmdb:{guids['tmdb']}", entry)
                    if guids.get("imdb"):
                        self._add(self.movies, f"imdb:{guids['imdb']}", entry)

                elif typ in ("show", "tvshow"):
                    season_num = entry.get("season_number")
                    if season_num in (None, "null"):
                        # Series main entry.
                        if norm_title:
                            self._add(self.shows, f"title:{norm_title}", entry)
                        for gt in ("tmdb", "imdb", "tvdb"):
                            if guids.get(gt):
                                self._add(self.shows, f"{gt}:{guids[gt]}", entry)
                    else:
                        # Season entry — every key carries a ":S{n}" suffix.
                        if norm_title:
                            self._add(
                                self.seasons,
                                f"title:{norm_title}:S{season_num}",
                                entry,
                            )
                        for gt in ("tmdb", "imdb", "tvdb"):
                            if guids.get(gt):
                                self._add(
                                    self.seasons,
                                    f"{gt}:{guids[gt]}:S{season_num}",
                                    entry,
                                )

                elif typ == "collection":
                    if norm_title:
                        self._add(self.collections, f"title:{norm_title}", entry)
            except Exception:
                # A single malformed row must not abort the whole index build.
                continue

    # ----- lookup ---------------------------------------------------------

    @staticmethod
    def _match(
        index: Dict[str, List[Dict]], priority_keys: List[str], values: Dict[str, Any]
    ) -> Tuple[List[Dict], Optional[str]]:
        """Return (entries, matched_key_name) for the first priority key that
        hits, or ([], None). Entries is the list of every library copy."""
        for key in priority_keys:
            value = values.get(key)
            if value and f"{key}:{value}" in index:
                return index[f"{key}:{value}"], key.upper()
        return [], None

    @staticmethod
    def _search_values(
        asset: Dict, *, season_number: Optional[int] = None,
        title_override: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Build the guid/title lookup values from a media/asset row. Season
        rows suffix EVERY key with ":S{n}" so guid keys match the season index
        (a bare guid would collide across a show's seasons)."""
        title = asset.get("title", "")
        values: Dict[str, Optional[str]] = {
            "tmdb": str(asset.get("tmdb_id")) if asset.get("tmdb_id") else None,
            "imdb": asset.get("imdb_id"),
            "tvdb": str(asset.get("tvdb_id")) if asset.get("tvdb_id") else None,
            "title": title_override or (normalize_titles(title) if title else None),
        }
        if season_number is not None:
            for k in ("tmdb", "imdb", "tvdb"):
                if values.get(k):
                    values[k] = f"{values[k]}:S{season_number}"
        return values

    def resolve(
        self,
        asset: Dict,
        *,
        media_type: str,
        season_number: Optional[int] = None,
        title_override: Optional[str] = None,
    ) -> Tuple[List[Dict], Optional[str]]:
        """Resolve a media/asset row to its Plex library entries.

        ``media_type`` selects the type-specific index ("movie" | "show" |
        "season" | "collection"), so a movie is never matched against a show
        library. Returns (entries, matched_key) — entries is one row per library
        copy (dedupe by library at the call site if needed). ([], None) on miss,
        which the caller may treat as a signal to fall back to a live search.
        """
        values = self._search_values(
            asset, season_number=season_number, title_override=title_override
        )
        if media_type == "movie":
            return self._match(self.movies, MOVIE_PRIORITY_KEYS, values)
        if media_type == "season":
            return self._match(self.seasons, SEASON_PRIORITY_KEYS, values)
        if media_type in ("show", "tvshow"):
            return self._match(self.shows, SHOW_PRIORITY_KEYS, values)
        if media_type == "collection":
            return self._match(self.collections, COLLECTION_PRIORITY_KEYS, values)
        return [], None

    def is_empty(self) -> bool:
        return not (self.movies or self.shows or self.seasons or self.collections)
