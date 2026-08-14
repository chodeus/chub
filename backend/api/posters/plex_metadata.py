"""Plex metadata (Poster Cleanarr) endpoints."""

import os
from typing import Any

from fastapi import Depends, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.api.utils import (
    BODY_TOO_LARGE,
    body_too_large_error,
    error,
    get_database,
    ok,
    read_json_object,
)
from backend.util.config import ConfigError
from backend.util.database import ChubDB
from backend.util.poster_cleanarr_settings import (
    build_cleanup_overrides,
    get_excluded_libraries,
    get_plex_path,
)
from backend.api.posters._shared import get_cleanarr_logger, router


@router.get("/plex-metadata/by-media")
async def list_plex_metadata_by_media(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    only_bloat: bool = Query(False),
    media_type: str = Query(
        "all",
        description="Filter by metadata_type label: movie, show, season, episode, artist, album, collection, all.",
    ),
    library_id: int = Query(
        0, description="Filter by Plex library_section_id. 0 = all."
    ),
    variant_kind: str = Query(
        "all",
        description="Filter to variants of a single kind (poster/art/banner/thumb/chapter/theme/other). Bundles with no matching variants are hidden.",
    ),
    logger: Any = Depends(get_cleanarr_logger),
):
    """
    Group Plex Metadata poster variants by their owning media item.

    Returns `{bundles, libraries, total, limit, offset, stats}`. Filters are
    applied *after* the scan (so the scan + cache is reusable across filter
    combinations). `libraries` lists every section that has at least one
    bundle in the unfiltered scan so the frontend can render a dropdown.
    """
    try:
        from backend.util.plex_metadata import (
            get_cached_scan,
            get_cached_transcoder,
        )

        plex_path = get_plex_path()
        if not plex_path:
            # Expected state on every Poster Cleanarr page mount before the
            # user has configured plex_path — not an operational failure, so
            # this must not be logger.error (the root ErrorNotifyHandler
            # forwards every ERROR record to Discord/Notifiarr).
            logger.debug("Scan requested but plex_path is not configured")
            return error(
                "Plex path is not configured",
                code="PLEX_PATH_UNSET",
                status_code=400,
            )

        # Read-only: never walk the Plex Metadata tree on the event loop. When
        # no fresh scan is cached, tell the client to enqueue a background
        # `plex_metadata_scan` job (POST /plex-metadata/scan) and poll it; the
        # job warms this cache off-loop and the client re-fetches once ready.
        scan = get_cached_scan(plex_path)
        if scan is None:
            return ok(
                "No scan cached — enqueue a scan",
                {
                    "bundles": [],
                    "libraries": [],
                    "media_types": [],
                    "variant_kinds": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "stats": None,
                    "transcoder": None,
                    "scan_required": True,
                },
            )
        transcoder = get_cached_transcoder(plex_path) or {
            "count": 0,
            "size_bytes": 0,
        }
        bundles = scan["bundles"]

        media_type = (media_type or "all").lower()
        variant_kind = (variant_kind or "all").lower()

        if media_type != "all":
            bundles = [
                b for b in bundles if (b.get("metadata_type_label") or "") == media_type
            ]
        if library_id:
            bundles = [b for b in bundles if b.get("library_section_id") == library_id]
        # Library opt-out (poster_cleanarr.excluded_libraries): hide excluded
        # libraries from the view. Mirrors the module's deletion-side deny-list
        # so what the user sees matches what a run would touch. The in-use set is
        # unaffected — this is display only.
        excluded_libs = {
            (n or "").strip().lower() for n in get_excluded_libraries()
        }
        if excluded_libs:
            bundles = [
                b
                for b in bundles
                if (b.get("library_name") or "").strip().lower() not in excluded_libs
            ]
        if variant_kind != "all":
            trimmed = []
            for b in bundles:
                kept = [v for v in b["variants"] if v.get("kind") == variant_kind]
                if kept:
                    trimmed.append({**b, "variants": kept})
            bundles = trimmed
        if only_bloat:
            bundles = [
                b for b in bundles if any(not v["active"] for v in b["variants"])
            ]
        total = len(bundles)
        page = bundles[offset : offset + limit]
        return ok(
            f"Retrieved {len(page)} of {total} bundles",
            {
                "bundles": page,
                "libraries": [
                    lib
                    for lib in scan.get("libraries", [])
                    if (lib.get("name") or "").strip().lower() not in excluded_libs
                ],
                "media_types": scan.get("media_types", []),
                "variant_kinds": scan.get("variant_kinds", []),
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": scan["stats"],
                "transcoder": transcoder,
            },
        )
    except Exception as e:
        logger.error(f"Error listing plex metadata bundles: {e}")
        return error(
            "Error listing plex metadata",
            code="PLEX_METADATA_LIST_ERROR",
            status_code=500,
        )


@router.get("/plex-metadata/bloat")
async def list_plex_metadata_bloat(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_cleanarr_logger),
):
    """Flat list of bloat variants across all bundles, largest first."""
    try:
        from backend.util.plex_metadata import bloat_flat_from_scan, get_cached_scan

        plex_path = get_plex_path()
        if not plex_path:
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        # Cache-only read; the scan job (POST /plex-metadata/scan) warms it.
        scan = get_cached_scan(plex_path)
        if scan is None:
            return ok(
                "No scan cached — enqueue a scan",
                {
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "stats": None,
                    "scan_required": True,
                },
            )
        items = bloat_flat_from_scan(scan)
        total = len(items)
        page = items[offset : offset + limit]
        return ok(
            f"Retrieved {len(page)} of {total} bloat files",
            {
                "items": page,
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": scan["stats"],
            },
        )
    except Exception as e:
        logger.error(f"Error listing plex metadata bloat: {e}")
        return error(
            "Error listing plex metadata bloat",
            code="PLEX_METADATA_BLOAT_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/cleanup")
async def run_plex_metadata_cleanup(
    request: Request,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cleanarr_logger),
):
    """
    Enqueue a `poster_cleanarr` job. Request body (all optional):
        {
          "mode": "report"|"move"|"remove"|"nothing",    # bloat-image mode
                                                         # ("nothing" skips bloat
                                                         #  so stale/orphan can
                                                         #  run on their own)
          "target_paths": [str, ...],                    # bloat subset
          "orphan_assets_enabled": bool,
          "orphan_assets_mode": "report"|"move"|"remove",
          "stale_duplicates_enabled": bool,
          "stale_duplicates_mode": "report"|"move"|"remove",
          "asset_dirs": [str, ...]                       # override
        }
    Each cleaner (bloat / orphan / stale) runs independently in its own mode.
    """
    try:
        body = await read_json_object(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        from backend.util.config import load_config

        config = load_config()
        try:
            overrides = build_cleanup_overrides(body, config)
        except ValueError as ve:
            logger.error(f"Invalid cleanup request: {ve}")
            return error("Invalid cleanup mode", code="INVALID_MODE", status_code=400)
        mode = overrides["mode"]

        payload = {
            "module_name": "poster_cleanarr",
            "overrides": overrides,
        }

        result = db.worker.enqueue_job("jobs", payload, job_type="module_run")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(
                f"Poster cleanarr cleanup enqueued (mode={mode}, job_id={job_id})"
            )
            return ok("Cleanup job enqueued", {"job_id": job_id, "mode": mode})
        return error(
            "Failed to enqueue cleanup", code="ENQUEUE_FAILED", status_code=500
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error enqueuing cleanup: {e}")
        return error(
            "Error enqueuing cleanup",
            code="CLEANUP_ENQUEUE_ERROR",
            status_code=500,
        )


@router.delete("/plex-metadata/variant")
async def delete_plex_metadata_variant(
    request: Request,
    logger: Any = Depends(get_cleanarr_logger),
):
    """Delete a single variant file. Body: `{path: str}`."""
    try:
        from backend.util.plex_metadata import delete_variant

        body = await read_json_object(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        path = body.get("path")
        if not isinstance(path, str) or not path:
            return error("Missing 'path'", code="MISSING_PATH", status_code=400)
        plex_path = get_plex_path()
        if not plex_path:
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        ok_ = delete_variant(path, plex_path=plex_path)
        if not ok_:
            logger.warning(
                f"UI delete rejected (outside metadata or I/O error): {path}"
            )
            return error(
                "Failed to delete variant (path outside Plex metadata or I/O error)",
                code="VARIANT_DELETE_FAILED",
                status_code=400,
            )
        logger.info(f"UI delete: {path}")
        return ok("Variant deleted", {"path": path})
    except Exception as e:
        logger.error(f"Error deleting variant: {e}")
        return error(
            "Error deleting variant",
            code="VARIANT_DELETE_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/set-active")
async def set_plex_metadata_active(
    request: Request,
    logger: Any = Depends(get_cleanarr_logger),
):
    """
    Make a specific variant the active poster in Plex. Body:
        { "rating_key": int, "path": str }

    Uses plexapi's `item.uploadPoster(filepath=...)` — Plex re-ingests the
    file and points the item's `user_thumb_url` at the new hash. The old
    variant stays on disk and becomes bloat (cleanable from the same UI).
    """
    try:
        from backend.util.plex_metadata import invalidate_cache, resolve_in_metadata_dir

        body = await read_json_object(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        rating_key = body.get("rating_key")
        path = body.get("path")
        if not rating_key or not isinstance(path, str) or not path:
            return error(
                "Missing rating_key or path",
                code="MISSING_PARAMS",
                status_code=400,
            )

        # Path-injection guard: only allow files inside Plex's Metadata dir.
        # Without this, a caller could upload ANY file on the server as a
        # Plex poster by passing an arbitrary filesystem path.
        plex_path = get_plex_path()
        if not plex_path:
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        safe_path = resolve_in_metadata_dir(path, plex_path)
        if safe_path is None:
            return error(
                "Path outside Plex metadata dir", code="INVALID_PATH", status_code=400
            )
        if not os.path.isfile(safe_path):
            return error(
                "Variant file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        from backend.util.config import load_config

        cfg = load_config()
        # Pick the first configured Plex instance — CHUB typically has one.
        plex_instances = getattr(getattr(cfg, "instances", None), "plex", None) or {}
        instance_cfg = (
            next(iter(plex_instances.values()), None) if plex_instances else None
        )
        if instance_cfg is None:
            return error(
                "No Plex instance configured",
                code="NO_PLEX_INSTANCE",
                status_code=400,
            )

        from plexapi.server import PlexServer
        from plexapi.exceptions import NotFound

        # The Plex connect + fetch + upload is blocking — run it off the event
        # loop. fetchItem raises NotFound (never returns None) on a bad rating
        # key, so catch that and return a 404 instead of falling through to the
        # broad handler's 500 (the old `is None` check was dead).
        def _apply_active():
            server = PlexServer(instance_cfg.url, instance_cfg.api)
            try:
                item = server.fetchItem(int(rating_key))
            except NotFound:
                return False
            item.uploadPoster(filepath=safe_path)
            return True

        applied = await run_in_threadpool(_apply_active)
        if not applied:
            return error("Plex item not found", code="ITEM_NOT_FOUND", status_code=404)
        invalidate_cache()
        logger.info(f"UI set-active: rating_key={rating_key} path={safe_path}")
        return ok(
            "Active poster updated", {"rating_key": rating_key, "path": safe_path}
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error setting active poster: {e}")
        return error(
            "Error setting active poster",
            code="SET_ACTIVE_ERROR",
            status_code=500,
        )


@router.get("/plex-metadata/variant-thumbnail")
async def get_plex_variant_thumbnail(
    request: Request,
    path: str = Query(...),
):
    """
    Serve a single variant file as an image. Plex stores these without a
    file extension so we send it as image/jpeg (Plex posters are JPEGs).
    Validates the path stays within Plex's Metadata/ dir.
    """
    from backend.util.plex_metadata import resolve_in_metadata_dir

    plex_path = get_plex_path()
    if not plex_path:
        return error(
            "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
        )
    real = resolve_in_metadata_dir(path, plex_path)
    if real is None or not os.path.isfile(real):
        return error("Invalid path", code="INVALID_PATH", status_code=400)
    return FileResponse(real, media_type="image/jpeg")


@router.get("/plex-metadata/kometa-assets-scan")
async def scan_kometa_assets(
    logger: Any = Depends(get_cleanarr_logger),
):
    """Return the cached Kometa stale-duplicate + orphan scan. Read-only and
    walk-free: the asset-dir walk runs in the background `kometa_assets_scan`
    job (POST /plex-metadata/kometa-scan), never on the event loop. When no
    scan is cached the client gets `scan_required` and enqueues one."""
    try:
        from backend.modules.poster_cleanarr import get_cached_kometa_assets

        cached = get_cached_kometa_assets()
        if cached is None:
            return ok(
                "No Kometa scan cached — enqueue a scan",
                {
                    "stale": [],
                    "orphans": [],
                    "stats": {"stale_count": 0, "orphan_count": 0},
                    "scan_required": True,
                },
            )
        return ok("Kometa asset scan complete", cached)
    except Exception as e:
        logger.error(f"Kometa asset scan read failed: {e}")
        return error(
            "Kometa asset scan read failed",
            code="KOMETA_SCAN_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/scan")
async def enqueue_plex_metadata_scan(
    request: Request,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cleanarr_logger),
):
    """Enqueue a background `plex_metadata_scan` job that warms the bundle +
    transcoder caches off the event loop. Returns a `job_id` the client polls
    (GET /jobs/{id}/log-tail) before re-fetching /by-media. Duplicate enqueues
    collapse to the in-flight scan."""
    try:
        plex_path = get_plex_path()
        if not plex_path:
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        result = db.worker.enqueue_job(
            "jobs", {"plex_path": plex_path}, job_type="plex_metadata_scan"
        )
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(f"Plex metadata scan enqueued (job_id={job_id})")
            return ok("Scan job enqueued", {"job_id": job_id})
        return error("Failed to enqueue scan", code="ENQUEUE_FAILED", status_code=500)
    except Exception as e:
        logger.error(f"Error enqueuing plex metadata scan: {e}")
        return error(
            "Error enqueuing scan",
            code="SCAN_ENQUEUE_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/kometa-scan")
async def enqueue_kometa_assets_scan(
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cleanarr_logger),
):
    """Enqueue a background `kometa_assets_scan` job that warms the stale/orphan
    cache off the event loop. Returns a `job_id` the client polls before
    re-fetching /kometa-assets-scan."""
    try:
        result = db.worker.enqueue_job("jobs", {}, job_type="kometa_assets_scan")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(f"Kometa assets scan enqueued (job_id={job_id})")
            return ok("Kometa scan job enqueued", {"job_id": job_id})
        return error(
            "Failed to enqueue Kometa scan", code="ENQUEUE_FAILED", status_code=500
        )
    except Exception as e:
        logger.error(f"Error enqueuing kometa assets scan: {e}")
        return error(
            "Error enqueuing Kometa scan",
            code="KOMETA_ENQUEUE_ERROR",
            status_code=500,
        )


# --- Parameterized poster ID endpoints ---
