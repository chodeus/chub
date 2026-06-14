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

from backend.util.helper import YEAR_MATCH_TOLERANCE
from backend.util.normalization import normalize_titles

# Priority order of match keys per media type (highest-confidence first). Guids
# beat titles; tvdb leads for shows (Sonarr's native id), tmdb for movies.
MOVIE_PRIORITY_KEYS = ["tmdb", "imdb", "title"]
SHOW_PRIORITY_KEYS = ["tvdb", "tmdb", "imdb", "title"]
SEASON_PRIORITY_KEYS = ["tvdb", "tmdb", "imdb", "title"]
COLLECTION_PRIORITY_KEYS = ["title"]
# Music: MusicBrainz id is the cross-source anchor; fall back to a normalized
# title (parent-scoped for albums, see _search_values / resolve).
ARTIST_PRIORITY_KEYS = ["mbid", "title"]
ALBUM_PRIORITY_KEYS = ["mbid", "title"]


def _coerce_year(value: Any) -> Optional[int]:
    """Best-effort int year from a cache/asset field that may be int, the TEXT
    "2007", or an empty/None/"None" placeholder. Returns None when absent or
    unparseable so callers can treat "no year" as "can't disambiguate"."""
    if value in (None, "", "None", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
        self.artists: Dict[str, List[Dict]] = {}
        self.albums: Dict[str, List[Dict]] = {}
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

                elif typ == "artist":
                    # MBID keys are lower-cased on both build and lookup sides
                    # (Plex guids can be mixed-case; media_cache/extract_mbid are
                    # lower) so an MBID match never silently falls back to title.
                    if guids.get("mbid"):
                        self._add(
                            self.artists, f"mbid:{str(guids['mbid']).lower()}", entry
                        )
                    if norm_title:
                        self._add(self.artists, f"title:{norm_title}", entry)

                elif typ == "album":
                    if guids.get("mbid"):
                        self._add(
                            self.albums, f"mbid:{str(guids['mbid']).lower()}", entry
                        )
                    # Scope the album title under its artist so identically
                    # named albums ("Greatest Hits") across artists don't
                    # collide. Fall back to the bare album title only when the
                    # parent is unknown.
                    parent_norm = entry.get("parent_normalized_title")
                    if norm_title and parent_norm:
                        self._add(
                            self.albums,
                            f"title:{parent_norm}::{norm_title}",
                            entry,
                        )
                    elif norm_title:
                        self._add(self.albums, f"title:{norm_title}", entry)
            except Exception:
                # A single malformed row must not abort the whole index build.
                continue

    # ----- lookup ---------------------------------------------------------

    @staticmethod
    def _disambiguate_by_year(
        entries: List[Dict], asset_year: Optional[int]
    ) -> List[Dict]:
        """Drop same-title collisions of the clearly-wrong year.

        A title-only match can return more than one item that shares a
        normalized title but is a different release (e.g. "3:10 to Yuma" 1957
        vs 2007). Without the year we'd hand back every copy and the caller
        could upload the wrong-year poster — or, when only the wrong-year item
        is in Plex, upload to it because Plex hasn't scanned ours yet.

        A candidate is dropped ONLY when both it and the asset carry a year and
        they differ by more than ``YEAR_MATCH_TOLERANCE`` (Plex's year can lag
        *arr/TMDB by a year — production vs release — so the same ±1 tolerance
        the live search uses applies here). Candidates with no year are kept, so
        a metadata gap can never cause a false skip. When nothing is dropped the
        original list is returned unchanged; when a wrong-year copy IS dropped
        the (possibly empty) survivors are returned — an empty result means the
        caller should treat it as a miss rather than match the wrong year.
        """
        target = _coerce_year(asset_year)
        if target is None:
            return entries
        kept: List[Dict] = []
        dropped_wrong_year = False
        for e in entries:
            ey = _coerce_year(e.get("year"))
            if ey is None or abs(ey - target) <= YEAR_MATCH_TOLERANCE:
                kept.append(e)
            else:
                dropped_wrong_year = True
        return kept if dropped_wrong_year else entries

    @staticmethod
    def _match(
        index: Dict[str, List[Dict]], priority_keys: List[str], values: Dict[str, Any]
    ) -> Tuple[List[Dict], Optional[str]]:
        """Return (entries, matched_key_name) for the first priority key that
        hits, or ([], None). Entries is the list of every library copy.

        Guid hits (tmdb/imdb/tvdb) are exact and returned as-is. A TITLE hit is
        year-disambiguated against ``values['year']`` so a same-title/different-
        year collision can't return the wrong release; if that leaves no
        year-correct copy the title key is treated as a miss (([], None))."""
        for key in priority_keys:
            value = values.get(key)
            if value and f"{key}:{value}" in index:
                entries = index[f"{key}:{value}"]
                if key == "title":
                    entries = PlexMediaIndex._disambiguate_by_year(
                        entries, values.get("year")
                    )
                    if not entries:
                        return [], None
                return entries, key.upper()
        return [], None

    @staticmethod
    def _search_values(
        asset: Dict, *, season_number: Optional[int] = None,
        title_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the guid/title lookup values from a media/asset row. Season
        rows suffix EVERY key with ":S{n}" so guid keys match the season index
        (a bare guid would collide across a show's seasons)."""
        title = asset.get("title", "")
        values: Dict[str, Any] = {
            "tmdb": str(asset.get("tmdb_id")) if asset.get("tmdb_id") else None,
            "imdb": asset.get("imdb_id"),
            "tvdb": str(asset.get("tvdb_id")) if asset.get("tvdb_id") else None,
            "mbid": (str(asset.get("musicbrainz_id")).lower()
                     if asset.get("musicbrainz_id") else None),
            "title": title_override or (normalize_titles(title) if title else None),
            # Carried for title-match year-disambiguation (see _match). Inert for
            # guid hits; None when the row has no year, which keeps current
            # behavior.
            "year": _coerce_year(asset.get("year")),
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
        if media_type == "artist":
            return self._match(self.artists, ARTIST_PRIORITY_KEYS, values)
        if media_type == "album":
            # Album titles are matched parent-scoped ("{artist}::{album}") to
            # avoid cross-artist collisions; MBID (when present) wins first.
            album_norm = normalize_titles(asset.get("title") or "")
            parent_norm = normalize_titles(asset.get("parent_title") or "")
            scoped = f"{parent_norm}::{album_norm}" if parent_norm else album_norm
            album_values = self._search_values(asset, title_override=scoped)
            return self._match(self.albums, ALBUM_PRIORITY_KEYS, album_values)
        return [], None

    def is_empty(self) -> bool:
        return not (
            self.movies
            or self.shows
            or self.seasons
            or self.collections
            or self.artists
            or self.albums
        )
