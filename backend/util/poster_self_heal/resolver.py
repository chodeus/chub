# backend/util/poster_self_heal/resolver.py
"""Decide whether a CL2K poster's embedded ids / title / year have drifted.

CL2K posters are always made for the user's library items, so the live
``media_cache`` row is the source of the current id set (tmdb/tvdb/imdb) — it
mirrors *arr/Plex, which sync from TMDB/TVDB. We match each poster to its library
row (id-first across all three ids, then title+year), rebuild the canonical DAPS
filename from that row's ids plus TMDB's canonical title/year (``get_details``),
and propose the rename when it differs from the current filename. One pass heals
id, title, and year drift together — a filename is canonical or it isn't.

``resolve_poster`` returns a proposal dict (shaped for poster_heal_review.upsert)
or None for a no-op (already canonical, no library match, or a transient TMDB
failure that must be retried rather than acted on).
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from backend.util.cl2k.naming import build_poster_filename
from backend.util.constants import asset_type_regex, season_number_regex
from backend.util.helper import extract_ids, extract_year
from backend.util.normalization import normalize_titles, parse_asset_filename

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


def _season_int(value: Any) -> Optional[int]:
    """Like _as_int but KEEPS 0 — season 0 is the Specials season, a real value
    (unlike an id, where 0 means 'absent')."""
    if value in (None, "", "None"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _season_collapsed(name: str) -> str:
    """Collapse a filename's season tag to a padding-insensitive, year-safe key:
    'Season 1' / 'Season 01' / 'Specials' (= Season 0) / 'Season 2026' all reduce
    to their integer value. Lets the resolver tell a real rename from a
    season-format-only difference — CHUB/Plex parse the season to an int and match
    identically, so reformatting it alone isn't worth a Drive rename."""
    return season_number_regex.sub(
        lambda m: f" - Season {int(m.group(1)) if m.group(1) is not None else 0}",
        name,
    )


def _imdb(value: Any) -> str:
    """Normalize an IMDb id to a comparable 'tt…' string, or '' when absent."""
    s = str(value).strip().lower() if value not in (None, "", "None") else ""
    return s if s.startswith("tt") else ""


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def poster_from_filename(filename: str) -> Optional[Dict[str, Any]]:
    """Parse a bare Drive filename into the poster dict ``resolve_poster``
    consumes — the live-Drive counterpart of a poster_cache row, for CL2K posters
    saved straight to Drive (never recorded in poster_cache). Mirrors
    poster_renamerr's own filename parsing so a Drive poster heals identically to
    a local one. ``file`` is the bare name (no directory) so apply renames only
    on Drive. ``asset_type`` is left for resolve_poster to refine from the matched
    library row (a season tag ⇒ show). Returns None for a non-image file."""
    _, ext = os.path.splitext(filename)
    if ext.lower() not in _IMAGE_EXTS:
        return None
    m = asset_type_regex.search(filename)
    if m:
        image_type = m.group(1).lower()
        base = asset_type_regex.sub("", filename).strip(" -_")
        title = parse_asset_filename(base + ext)
        normalized_title = normalize_titles(base)
    else:
        image_type = "poster"
        title = parse_asset_filename(filename)
        normalized_title = normalize_titles(filename)
    tmdb_id, tvdb_id, imdb_id = extract_ids(filename)
    match = season_number_regex.search(filename)
    season_number = (
        int(match.group(1)) if match and match.group(1) else (0 if match else None)
    )
    return {
        "title": title,
        "normalized_title": normalized_title,
        "year": extract_year(filename) or extract_year(title),
        "tmdb_id": tmdb_id,
        "tvdb_id": tvdb_id,
        "imdb_id": imdb_id,
        "season_number": season_number,
        "image_type": image_type,
        "asset_type": "show" if season_number is not None else None,
        "file": filename,
    }


def index_media(media_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build id + title indexes over matched media_cache rows. First write wins
    per id (media_cache is deduped per identity already)."""
    by_tmdb: Dict[int, Dict[str, Any]] = {}
    by_tvdb: Dict[int, Dict[str, Any]] = {}
    by_imdb: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for m in media_rows:
        if not m.get("matched"):
            continue
        t = _as_int(m.get("tmdb_id"))
        if t and t not in by_tmdb:
            by_tmdb[t] = m
        v = _as_int(m.get("tvdb_id"))
        if v and v not in by_tvdb:
            by_tvdb[v] = m
        i = _imdb(m.get("imdb_id"))
        if i and i not in by_imdb:
            by_imdb[i] = m
        nt = m.get("normalized_title") or _norm(m.get("title"))
        if nt:
            by_title.setdefault(nt, []).append(m)
    return {"tmdb": by_tmdb, "tvdb": by_tvdb, "imdb": by_imdb, "title": by_title}


def _find_media(
    poster: Dict[str, Any], idx: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], str, bool]:
    """Match a poster to one live media row.

    Returns (media_row, match_kind, ambiguous). ``match_kind`` is "id" (a high-
    confidence id hit on any of tmdb/tvdb/imdb), "title" (a unique title+year
    hit), or "". ``ambiguous`` is True when title+year matched >1 row.
    """
    t = _as_int(poster.get("tmdb_id"))
    if t and t in idx["tmdb"]:
        return idx["tmdb"][t], "id", False
    v = _as_int(poster.get("tvdb_id"))
    if v and v in idx["tvdb"]:
        return idx["tvdb"][v], "id", False
    i = _imdb(poster.get("imdb_id"))
    if i and i in idx["imdb"]:
        return idx["imdb"][i], "id", False

    nt = poster.get("normalized_title") or _norm(poster.get("title"))
    candidates = idx["title"].get(nt, []) if nt else []
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
        return candidates[0], "title", False
    if len(candidates) > 1:
        return None, "", True
    return None, "", False


def _canonical_title_year(
    tmdb_id: Optional[int],
    media_type: str,
    tmdb_client,
    fallback_title: str,
    fallback_year: Optional[int],
) -> Tuple[Optional[str], Optional[int], bool]:
    """(title, year, ok). ok=False means a transient TMDB failure → retry later.

    Uses TMDB get_details for the canonical title/year (the user's chosen source
    of truth), falling back to the library values when TMDB has nothing useful.
    """
    if not tmdb_id:
        return fallback_title, fallback_year, True
    details = tmdb_client.get_details(tmdb_id, media_type)
    if details is None:
        return None, None, False  # transient — don't act
    title = fallback_title
    year = fallback_year
    if details.get("verified"):
        if details.get("title"):
            title = details["title"]
        if _as_int(details.get("year")):
            year = _as_int(details.get("year"))
    return title, year, True


def resolve_poster(
    poster: Dict[str, Any],
    media_index: Dict[str, Any],
    drive_folder_id: Optional[str],
    tmdb_client,
    cfg,
) -> Optional[Dict[str, Any]]:
    """Return a poster_heal_review proposal dict, or None for a no-op / retry."""
    asset_type = poster.get("asset_type") or "movie"
    cur_name = os.path.basename(poster.get("file", ""))
    _, ext = os.path.splitext(poster.get("file", ""))
    title_old = poster.get("title") or ""
    old_tmdb = _as_int(poster.get("tmdb_id"))
    old_tvdb = _as_int(poster.get("tvdb_id"))
    old_imdb = _imdb(poster.get("imdb_id"))
    old_year = _as_int(poster.get("year"))
    has_any_id = bool(old_tmdb or old_tvdb or old_imdb)

    if not has_any_id and not cfg.backfill_ids:
        return None  # id-less poster, backfill disabled

    media, match_kind, ambiguous = _find_media(poster, media_index)

    if not media:
        if ambiguous:
            # Multiple library items share this title — can't safely pick one.
            return {
                "poster_file": poster.get("file"),
                "drive_folder_id": drive_folder_id,
                "asset_type": asset_type,
                "drift_type": "ambiguous",
                "current_filename": cur_name,
                "proposed_filename": cur_name,
                "tmdb_id_old": old_tmdb,
                "tmdb_id_new": None,
                "title_old": title_old,
                "title_new": title_old,
                "confidence": 0.5,
                "reason": "matches multiple library items by title — pick the right one",
                "status": "pending",
            }
        return None  # no library match (or non-library poster) — leave it alone

    # The matched library row is authoritative for the media type — a live-Drive
    # poster may carry none (asset_type=None). Drives the TMDB endpoint and the
    # canonical filename's kind.
    resolved_type = media.get("asset_type") or asset_type
    media_type = _media_type(resolved_type)

    # Canonical id set comes from the live library row; title/year from TMDB.
    new_tmdb = _as_int(media.get("tmdb_id")) or old_tmdb
    new_tvdb = _as_int(media.get("tvdb_id")) or old_tvdb
    new_imdb = _imdb(media.get("imdb_id")) or old_imdb
    title_new, year_new, ok = _canonical_title_year(
        new_tmdb,
        media_type,
        tmdb_client,
        media.get("title") or title_old,
        _as_int(media.get("year")) or old_year,
    )
    if not ok:
        return None  # transient TMDB failure — retry next run

    # A season/specials poster heals the SHOW's identity (it matches the show's
    # media row) while keeping its own season tag: pass kind="season" so
    # build_poster_filename re-emits ` - Season NN` / ` - Specials` (0 = Specials,
    # which is why _season_int keeps 0). Otherwise the tag would be dropped.
    season = _season_int(poster.get("season_number"))
    new_name = build_poster_filename(
        kind="season" if season is not None else resolved_type,
        title=title_new or title_old,
        year=year_new,
        tmdb_id=new_tmdb,
        tvdb_id=new_tvdb,
        imdb_id=new_imdb or None,
        season_number=season,
        ext=ext or ".jpg",
        asset_suffix=_ASSET_SUFFIX.get(poster.get("image_type") or "poster", ""),
    )
    if new_name == cur_name:
        return None  # already canonical

    # Label what changed (the current -> proposed filename shows the full detail).
    changed: List[str] = []
    if old_tmdb != new_tmdb:
        changed.append("backfill" if not old_tmdb else "tmdb")
    if new_tvdb and old_tvdb != new_tvdb:
        changed.append("tvdb")
    if new_imdb and old_imdb != new_imdb:
        changed.append("imdb")
    if _norm(title_old) != _norm(title_new):
        changed.append("title")
    if year_new and old_year != year_new:
        changed.append("year")

    # When no id/title/year actually changed, a leftover filename difference that
    # is ONLY the season tag's formatting (Season 1 ≡ Season 01, Specials ≡
    # Season 0, year seasons like Season 2026) is not real drift — the matcher
    # keys on the parsed integer season — so skip the pointless rename.
    if not changed and _season_collapsed(cur_name) == _season_collapsed(new_name):
        return None
    drift_type = "+".join(changed) or "rename"

    return {
        "poster_file": poster.get("file"),
        "drive_folder_id": drive_folder_id,
        "asset_type": resolved_type,
        "drift_type": drift_type,
        "current_filename": cur_name,
        "proposed_filename": new_name,
        "tmdb_id_old": old_tmdb,
        "tmdb_id_new": new_tmdb,
        "title_old": title_old,
        "title_new": title_new,
        "confidence": 0.95 if match_kind == "id" else 0.9,
        "reason": (
            "matched the live library item by id"
            if match_kind == "id"
            else "matched the live library item by title + year"
        ),
        "status": "proposed",
    }
