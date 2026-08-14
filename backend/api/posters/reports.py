"""Read-only poster reports: low-resolution, added-since, matched, applied."""

from typing import Any, Optional

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from backend.api.posters._shared import router
from backend.api.utils import (
    error,
    get_database,
    get_logger,
    ok,
)
from backend.util.database import ChubDB


@router.get(
    "/low-resolution",
    summary="List posters below a resolution threshold",
    description="Return poster_cache rows where recorded width is below "
    "`min_width`. Run /backfill-dimensions first to populate unset rows.",
)
async def list_low_resolution_posters(
    min_width: int = 1000,
    limit: int = 200,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        rows = db.poster.find_low_resolution(
            min_width=max(1, min_width), limit=max(1, min(limit, 1000))
        )
        return ok(
            f"{len(rows)} posters below {min_width}px",
            {"items": rows, "min_width": min_width},
        )
    except Exception as e:
        logger.error(f"Error listing low-resolution posters: {e}")
        return error(
            "Error listing low-resolution posters",
            code="LOW_RES_ERROR",
            status_code=500,
        )


@router.get(
    "/added-since",
    summary="Posters added since ISO cutoff",
    description="Return poster_cache rows whose created_at is >= the given "
    "ISO-8601 cutoff. Enables `period=30d`-style frontend filters.",
)
async def list_posters_added_since(
    cutoff: str,
    limit: int = 500,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        rows = db.poster.added_since(cutoff, limit=max(1, min(limit, 2000)))
        return ok(
            f"{len(rows)} posters added since {cutoff}",
            {"items": rows, "cutoff": cutoff},
        )
    except Exception as e:
        logger.error(f"Error listing posters added_since: {e}")
        return error(
            "Error listing posters added_since",
            code="ADDED_SINCE_ERROR",
            status_code=500,
        )


@router.get(
    "/recently-matched",
    summary="Posters most recently matched to media",
    description="Return poster_cache rows for the media/collections most "
    "recently matched by poster_renamerr, newest first. Reflects what CHUB "
    "actually applied to your library, not cache insertion order.",
)
async def list_recently_matched(
    limit: int = 50,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        rows = db.media.get_recently_matched(limit=max(1, min(limit, 500)))
        return ok(f"{len(rows)} recently matched posters", {"items": rows})
    except Exception as e:
        logger.error(f"Error listing recently matched posters: {e}")
        return error(
            "Error listing recently matched posters",
            code="RECENTLY_MATCHED_ERROR",
            status_code=500,
        )


@router.get(
    "/applied",
    summary="Matched media using a given poster variant",
    description="List media whose applied poster is of the given style variant "
    "(e.g. CL2K, MM2K), optionally filtered by asset type. Lets a user drill "
    "into a variant to request the other one.",
)
async def list_applied_media_by_style(
    style: str,
    type: Optional[str] = Query(
        None, description="Filter by asset type: movie, show, season"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        result = db.stats.get_applied_media_by_style(
            style, asset_type=type, limit=limit, offset=offset
        )
        return ok(
            f"{result['total']} matched media using {style}",
            {**result, "style": style, "limit": limit, "offset": offset},
        )
    except Exception as e:
        logger.error(f"Error listing applied media by style: {e}")
        return error(
            "Error listing applied media",
            code="APPLIED_MEDIA_ERROR",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Plex Metadata / Poster Cleanarr endpoints
# ---------------------------------------------------------------------------
