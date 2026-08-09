# backend/util/cl2k/tmdb_art.py
"""TMDB art-picker helpers for the CL2K maker.

Free functions over a TMDBClient instance (first argument), kept here so
backend/util/tmdb.py stays identical to main — the maker is the only
consumer. They deliberately reuse the client's private plumbing
(``_memo``/``_memo_lock`` cache, ``_request_with_retry``,
``_normalize_langs``, ``_fetch_images``); if those internals change on
main, this module is the one place to follow suit.
"""

from typing import Any, Dict, List, Union


def _image_mt(media_type: str) -> str:
    """Map a media kind to the TMDB path segment."""
    mt = (media_type or "").lower()
    if mt == "movie":
        return "movie"
    if mt == "collection":
        return "collection"
    return "tv"


def list_images(
    tmdb, tmdb_id: int, media_type: str, languages: Union[str, List[str]] = "en"
) -> Any:
    """Return the full TMDB images payload (every logo + backdrop) for a
    media item — for the CL2K art picker.

    Unlike TMDBClient.get_images (which auto-picks one of each), this exposes
    all candidates so callers can choose by resolution. Returns None on a
    transient failure, or ``{"logos": [], "backdrops": []}`` for a bad id.
    """
    if not tmdb.enabled or not tmdb_id:
        return None
    mt = _image_mt(media_type)
    key = ("list_images", str(tmdb_id), mt)
    with tmdb._memo_lock:
        if key in tmdb._memo:
            return tmdb._memo[key]
    result = tmdb._fetch_images(tmdb_id, mt, languages)
    with tmdb._memo_lock:
        tmdb._memo[key] = result
    return result


def list_season_images(
    tmdb,
    tmdb_id: int,
    season_number: int,
    languages: Union[str, List[str]] = "en",
) -> Any:
    """Return the TMDB season-level posters for a show season — for the CL2K
    art picker (a season has its own portrait 2:3 key-art, distinct from the
    show backdrops). GET /3/tv/{id}/season/{n}/images.

    Returns ``{"posters": [...]}`` (textless art included via
    ``include_image_language``), or None on a transient failure / disabled.
    """
    if not tmdb.enabled or not tmdb_id or season_number is None:
        return None
    key = ("list_season_images", str(tmdb_id), str(season_number))
    with tmdb._memo_lock:
        if key in tmdb._memo:
            return tmdb._memo[key]
    url = f"{tmdb.BASE}/tv/{tmdb_id}/season/{season_number}/images"
    langs = tmdb._normalize_langs(languages)
    params = {
        "api_key": tmdb.cfg.apikey,
        "include_image_language": ",".join([*langs, "null"]),
    }
    resp = tmdb._request_with_retry(
        url, params, what=f"tv/{tmdb_id}/season/{season_number}/images"
    )
    if resp is None:
        return None
    if resp.status_code == 404:
        result: Any = {"posters": []}
    elif not resp.ok:
        tmdb.logger.warning(
            f"TMDB returned {resp.status_code} for tv/{tmdb_id}/season/{season_number}/images"
        )
        return None
    else:
        try:
            result = resp.json()
        except ValueError:
            return None
    with tmdb._memo_lock:
        tmdb._memo[key] = result
    return result


def search_titles(tmdb, query: str, media_type: str) -> List[Dict[str, Any]]:
    """Search TMDB by title for the maker's entry point.

    ``media_type`` is movie / show / collection. Returns the raw results
    list (id, title/name, year, overview, ...), or [] on failure / disabled.
    """
    if not tmdb.enabled or not query:
        return []
    mt = _image_mt(media_type)
    url = f"{tmdb.BASE}/search/{mt}"
    params = {"api_key": tmdb.cfg.apikey, "query": query}
    resp = tmdb._request_with_retry(url, params, what=f"search/{mt}")
    if resp is None or not resp.ok:
        return []
    try:
        return resp.json().get("results", [])
    except ValueError:
        return []


def external_ids(tmdb, tmdb_id: int, media_type: str) -> Dict[str, Any]:
    """Return ``{tvdb_id, imdb_id}`` from TMDB for a movie/show.

    Used by the CL2K maker to auto-populate ids when a title is picked from
    search, so generated filenames match TVDB/IMDB-keyed libraries without
    manual entry. Collections have no external_ids endpoint (returns empty).
    Missing ids come back as None; ``{}``-ish on any failure / disabled.
    """
    if not tmdb.enabled or not tmdb_id:
        return {"tvdb_id": None, "imdb_id": None}
    mt = _image_mt(media_type)
    if mt == "collection":
        return {"tvdb_id": None, "imdb_id": None}
    key = ("external_ids", str(tmdb_id), mt)
    with tmdb._memo_lock:
        if key in tmdb._memo:
            return tmdb._memo[key]
    url = f"{tmdb.BASE}/{mt}/{tmdb_id}/external_ids"
    params = {"api_key": tmdb.cfg.apikey}
    resp = tmdb._request_with_retry(url, params, what=f"{mt}/{tmdb_id}/external_ids")
    out: Dict[str, Any] = {"tvdb_id": None, "imdb_id": None}
    if resp is not None and resp.ok:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        tvdb = data.get("tvdb_id")
        imdb = data.get("imdb_id")
        out["tvdb_id"] = tvdb if isinstance(tvdb, int) else None
        out["imdb_id"] = imdb or None
    with tmdb._memo_lock:
        tmdb._memo[key] = out
    return out
