# backend/util/poster_self_heal/resolver.py
"""Decide whether a CL2K poster's embedded id / title has drifted from TMDB.

CL2K posters are always made for the user's library items, so we bridge
"stale id -> current id" through media_cache (matched by title+year, since a
stale id can't match by id) and take the *canonical title* from TMDB
``get_details`` — keeping TMDB as the source of truth the user picked while
avoiding a TMDB free-text search.

``resolve_poster`` returns a proposal dict (shaped for poster_heal_review.upsert)
or None when there's nothing to do (no drift, or a transient TMDB failure that
must be retried rather than acted on).
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from backend.util.cl2k.naming import build_poster_filename
from backend.util.normalization import normalize_titles

YEAR_TOLERANCE = 1

# poster_cache image_type -> the asset-tag suffix build_poster_filename appends.
_ASSET_SUFFIX = {
    "poster": "",
    "logo": " - Logo",
    "background": " - Background",
    "squareart": " - SquareArt",
}


def _media_type(asset_type: Optional[str]) -> str:
    return "movie" if asset_type == "movie" else "tv"


def _norm(value: Optional[str]) -> str:
    return normalize_titles(value) if value else ""


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "", "None", 0, "0") else None
    except (TypeError, ValueError):
        return None


def index_media(media_rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group matched media_cache rows by normalized title for title+year lookup."""
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for m in media_rows:
        if not m.get("matched"):
            continue
        nt = m.get("normalized_title") or _norm(m.get("title"))
        if nt:
            by_title.setdefault(nt, []).append(m)
    return by_title


def _find_media(
    poster: Dict[str, Any], media_index: Dict[str, List[Dict[str, Any]]]
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Match a poster to a single live media row by title (+year when present).

    Returns (media_row, ambiguous). ``ambiguous`` is True when >1 candidate
    survives — the caller should queue it for manual resolution rather than guess.
    """
    nt = poster.get("normalized_title") or _norm(poster.get("title"))
    if not nt:
        return None, False
    candidates = media_index.get(nt, [])
    poster_year = _as_int(poster.get("year"))
    if poster_year is not None:
        yeared = [
            m
            for m in candidates
            if _as_int(m.get("year")) is not None
            and abs(_as_int(m.get("year")) - poster_year) <= YEAR_TOLERANCE
        ]
        if yeared:
            candidates = yeared
    if len(candidates) == 1:
        return candidates[0], False
    if len(candidates) > 1:
        return None, True
    return None, False


def _proposed_name(poster: Dict[str, Any], title: str, tmdb_id: Optional[int]) -> str:
    """Build the canonical DAPS filename the poster should have."""
    _, ext = os.path.splitext(poster.get("file", ""))
    return build_poster_filename(
        kind=poster.get("asset_type") or "movie",
        title=title,
        year=_as_int(poster.get("year")),
        tmdb_id=tmdb_id,
        tvdb_id=_as_int(poster.get("tvdb_id")),
        imdb_id=poster.get("imdb_id") or None,
        season_number=_as_int(poster.get("season_number")),
        ext=ext or ".jpg",
        asset_suffix=_ASSET_SUFFIX.get(poster.get("image_type") or "poster", ""),
    )


def _canonical_title(tmdb_id: int, media_type: str, tmdb_client, fallback: str) -> str:
    details = tmdb_client.get_details(tmdb_id, media_type)
    if details and details.get("verified") and details.get("title"):
        return details["title"]
    return fallback


def resolve_poster(
    poster: Dict[str, Any],
    media_index: Dict[str, List[Dict[str, Any]]],
    drive_folder_id: Optional[str],
    tmdb_client,
    cfg,
) -> Optional[Dict[str, Any]]:
    """Return a poster_heal_review proposal dict, or None for no-op / retry-later."""
    asset_type = poster.get("asset_type") or "movie"
    media_type = _media_type(asset_type)
    cur_name = os.path.basename(poster.get("file", ""))
    title_old = poster.get("title") or ""
    old_tmdb = _as_int(poster.get("tmdb_id"))

    def proposal(drift_type, tmdb_new, title_new, confidence, reason, status):
        new_name = _proposed_name(poster, title_new, tmdb_new)
        if new_name == cur_name:
            return None
        return {
            "poster_file": poster.get("file"),
            "drive_folder_id": drive_folder_id,
            "asset_type": asset_type,
            "drift_type": drift_type,
            "current_filename": cur_name,
            "proposed_filename": new_name,
            "tmdb_id_old": old_tmdb,
            "tmdb_id_new": tmdb_new,
            "title_old": title_old,
            "title_new": title_new,
            "confidence": confidence,
            "reason": reason,
            "status": status,
        }

    if old_tmdb:
        details = tmdb_client.get_details(old_tmdb, media_type)
        if details is None:
            return None  # transient TMDB failure — retry next run, don't act
        if details.get("verified"):
            # id is valid; only the title may have drifted.
            if not cfg.heal_titles:
                return None
            canon = details.get("title")
            if canon and _norm(canon) != _norm(title_old):
                return proposal(
                    "title",
                    old_tmdb,
                    canon,
                    0.95,
                    "TMDB title changed since the poster was named",
                    "proposed",
                )
            return None
        # verified is False -> the embedded id no longer exists on TMDB
        # (merged/removed). Re-resolve through the live library by title+year.
        if not cfg.heal_ids:
            return None
        media, ambiguous = _find_media(poster, media_index)
        if media:
            new_id = _as_int(media.get("tmdb_id"))
            if new_id and new_id != old_tmdb:
                title_new = _canonical_title(
                    new_id, media_type, tmdb_client, media.get("title") or title_old
                )
                return proposal(
                    "id",
                    new_id,
                    title_new,
                    0.9,
                    "embedded TMDB id no longer exists; matched a live library item",
                    "proposed",
                )
            return None
        if ambiguous:
            return proposal(
                "id",
                None,
                title_old,
                0.5,
                "embedded TMDB id no longer exists; multiple library items share "
                "this title — pick the right one",
                "pending",
            )
        return None

    # No embedded id -> backfill from the live library.
    if not cfg.backfill_ids:
        return None
    media, ambiguous = _find_media(poster, media_index)
    if media:
        new_id = _as_int(media.get("tmdb_id"))
        if new_id:
            title_new = _canonical_title(
                new_id, media_type, tmdb_client, media.get("title") or title_old
            )
            return proposal(
                "backfill",
                new_id,
                title_new,
                0.85,
                "resolved a TMDB id for an id-less poster from the live library",
                "proposed",
            )
        return None
    if ambiguous:
        return proposal(
            "backfill",
            None,
            title_old,
            0.5,
            "id-less poster matches multiple library items — pick the right one",
            "pending",
        )
    return None
