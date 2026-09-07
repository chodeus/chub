"""Plex artwork source for the CL2K maker (:full-image).

Resolves a media item to its Plex ratingKey via the ``plex_media_cache`` (the
same snapshot asset_renamerr already syncs) and fetches that item's clearLogos,
art (backgrounds) and posters through plexapi.

READ-ONLY by design: it never uploads, selects, or deletes anything — so it
cannot move an asset into or out of the in-use set and therefore can't trigger
any Poster Cleanarr bloat removal. Kept here rather than in the shared
``backend/util/plex.py`` because the CL2K maker is part of the :full image and
shared files must stay byte-identical with main.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

# Plex stores TV shows under asset_type "show"; tolerate "tvshow" defensively.
_TV_TYPES = {"show", "tvshow"}


def _coerce_guids(value: Any) -> Dict[str, Any]:
    """plex_media_cache.guids is a JSON dict ({"tmdb":"123",...}); tolerate a
    pre-parsed dict or a bad value (→ empty)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _matches(
    guids: Dict[str, Any],
    tmdb_id: Optional[int],
    tvdb_id: Optional[int],
    imdb_id: Optional[str],
) -> bool:
    if tmdb_id and str(guids.get("tmdb")) == str(tmdb_id):
        return True
    if tvdb_id and str(guids.get("tvdb")) == str(tvdb_id):
        return True
    if imdb_id and guids.get("imdb") == imdb_id:
        return True
    return False


def _resolve(
    full_config,
    db,
    *,
    media_type: str,
    tmdb_id: Optional[int],
    tvdb_id: Optional[int],
    imdb_id: Optional[str],
) -> Tuple[Optional[Any], Optional[str]]:
    """Return ``(instance_cfg, rating_key)`` for the first enabled Plex instance
    whose cache holds the item (guid match, type-gated), else ``(None, None)``.

    Type-gating matters because tmdb movie ids and tv ids are separate
    namespaces both stored under the ``tmdb`` guid key — without it a movie
    could resolve when a show was requested, or vice-versa."""
    want = "movie" if (media_type or "").lower() == "movie" else "show"
    plex = getattr(full_config.instances, "plex", {}) or {}
    for name, cfg in plex.items():
        if not (getattr(cfg, "enabled", True) and cfg.url and cfg.api):
            continue
        for row in db.plex.get_by_instance(name) or []:
            at = (row.get("asset_type") or "").lower()
            if want == "movie" and at != "movie":
                continue
            if want == "show" and at not in _TV_TYPES:
                continue
            if _matches(_coerce_guids(row.get("guids")), tmdb_id, tvdb_id, imdb_id):
                return cfg, row.get("plex_id")
    return None, None


def _proxy_url(src: str) -> str:
    """Browser-facing URL for a local Plex image: the CL2K proxy fetches it
    server-side (re-minting the token) so the X-Plex-Token never reaches the
    client. The <img> appends a short-lived stream token when loading it."""
    return f"/api/cl2k-maker/plex-art?src={quote(src, safe='')}"


def _img_urls(server, key: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a plexapi resource ``.key`` to ``(file_path, url)``. Remote-provider
    keys (themoviedb/gracenote) are already absolute, tokenless https — both are
    that URL. Local/uploaded keys (``/library/metadata/...``) would leak the
    X-Plex-Token, so BOTH become the CL2K proxy path carrying the tokenless Plex
    URL in ``?src=``: the browser loads it token-free (the proxy fetches
    server-side) and ``image_fetch.download`` unwraps ``?src=`` and re-mints the
    token. Using one value for both means every consumer — picker <img>, selected
    art previews, and the backend generate fetch — is handled uniformly."""
    if not key:
        return None, None
    if key.startswith("http://") or key.startswith("https://"):
        return key, key
    proxy = _proxy_url(server.url(key, includeToken=False))
    return proxy, proxy


def plex_images(
    full_config,
    db,
    logger,
    *,
    kind: str,
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return ``{logos, backdrops, posters}`` of Plex artwork for the item.

    Each entry is ``{file_path, url, provider, selected}``. On any miss the lists
    are empty and a ``reason`` string explains why (no Plex configured, item not
    in a synced library, Plex unreachable) so the picker can show a clear empty
    state instead of erroring. Note: Plex art objects carry no dimensions, so
    width/height are omitted (the picker tolerates that)."""
    empty: Dict[str, Any] = {"logos": [], "backdrops": [], "posters": []}
    plex = getattr(full_config.instances, "plex", {}) or {}
    if not plex:
        return {**empty, "reason": "No Plex instance is configured."}

    cfg, rating_key = _resolve(
        full_config,
        db,
        media_type=kind,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    if not rating_key:
        return {**empty, "reason": "Not found in a synced Plex library."}

    try:
        from plexapi.server import PlexServer

        server = PlexServer(cfg.url, cfg.api)
        item = server.fetchItem(int(rating_key))
    except Exception as exc:  # connection / fetch failure — degrade gracefully
        logger.warning(f"cl2k: Plex artwork fetch failed (key={rating_key}): {exc}")
        return {**empty, "reason": "Could not reach Plex."}

    out: Dict[str, Any] = {"logos": [], "backdrops": [], "posters": []}
    # plexapi method -> our bucket. arts() are backgrounds.
    for method, bucket in (
        ("logos", "logos"),
        ("arts", "backdrops"),
        ("posters", "posters"),
    ):
        fetch = getattr(item, method, None)
        if not callable(fetch):
            continue
        try:
            candidates: List[Any] = list(fetch())
        except Exception as exc:
            logger.debug(f"cl2k: Plex {method}() failed: {exc}")
            continue
        for res in candidates:
            file_path, url = _img_urls(server, getattr(res, "key", None))
            if not file_path:
                continue
            out[bucket].append(
                {
                    "file_path": file_path,
                    "url": url,
                    "provider": getattr(res, "provider", None),
                    "selected": bool(getattr(res, "selected", False)),
                }
            )
    return out
