"""Poster/artwork matching endpoints: matched, unmatched, and per-media match actions."""

import datetime
import os
from typing import Any

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from backend.api.posters._shared import router
from backend.api.utils import (
    error,
    get_database,
    get_logger,
    ok,
)
from backend.modules.unmatched_assets import UnmatchedAssets
from backend.util.asset_candidates import rank_candidates
from backend.util.database import ChubDB
from backend.util.database.poster_cache import ARTWORK_IMAGE_TYPES


@router.get(
    "/matched/stats",
    summary="Get matched poster statistics",
    description="Retrieve aggregated statistics for matched poster operations.",
    responses={
        200: {
            "description": "Matched poster statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Matched posters statistics retrieved",
                        "data": {
                            "matched_posters_stats": {
                                "total_matched": 150,
                                "uploaded": 120,
                                "pending": 30,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def get_matched_poster_stats(
    logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> JSONResponse:
    """
    Retrieve statistics for matched poster operations.

    Returns aggregated data about poster matching success rates,
    upload status, and processing metrics for monitoring purposes.

    Returns:
        Matched poster statistics and metrics
    """
    try:
        logger.debug("Serving GET /api/posters/matched/stats")

        stats = db.stats.get_matched_posters_stats()

        return ok(
            "Matched posters statistics retrieved",
            {"matched_posters_stats": stats},
        )

    except Exception as e:
        logger.error(f"Error retrieving matched posters stats: {e}")
        return error(
            "Error retrieving matched posters statistics",
            code="MATCHED_POSTERS_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/unmatched/stats",
    summary="Get unmatched assets statistics",
    description="Retrieve statistics for unmatched poster assets and analyze processing needs.",
    responses={
        200: {
            "description": "Unmatched assets statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Unmatched assets statistics retrieved",
                        "data": {
                            "summary": {
                                "total_unmatched": 25,
                                "needs_review": 15,
                                "auto_processable": 10,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def get_unmatched_assets_stats(logger: Any = Depends(get_logger)) -> JSONResponse:
    """
    Retrieve statistics for unmatched poster assets.

    Analyzes unmatched assets to provide summary statistics
    about files that need manual review or can be automatically
    processed for poster matching.

    Returns:
        Unmatched assets summary and processing recommendations
    """
    try:
        logger.debug("Serving GET /api/posters/unmatched/stats")
        unmatched_logger = logger.get_adapter("UnmatchedStats")

        unmatched = UnmatchedAssets(logger=unmatched_logger)
        stats = unmatched.get_stats_adhoc()

        return ok(
            "Unmatched assets statistics retrieved",
            {"summary": stats.get("summary", {})},
        )

    except Exception as e:
        logger.error(f"Error retrieving unmatched stats: {e}")
        return error(
            "Error retrieving unmatched assets statistics",
            code="UNMATCHED_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/unmatched/details",
    summary="Get detailed unmatched assets list",
    description="Retrieve per-item unmatched assets with external IDs for poster lookup.",
)
async def get_unmatched_assets_details(
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Return the full unmatched items list with summary and external IDs."""
    try:
        logger.debug("Serving GET /api/posters/unmatched/details")
        unmatched_logger = logger.get_adapter("UnmatchedDetails")

        unmatched = UnmatchedAssets(logger=unmatched_logger)
        stats = unmatched.get_stats_adhoc()

        return ok(
            "Unmatched assets details retrieved",
            {
                "summary": stats.get("summary", {}),
                "unmatched": stats.get("unmatched", {}),
                "needs_review": stats.get("needs_review", []),
                "ignored": stats.get("ignored", []),
                "locked": stats.get("locked", []),
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving unmatched details: {e}")
        return error(
            "Error retrieving unmatched assets details",
            code="UNMATCHED_DETAILS_ERROR",
            status_code=500,
        )


@router.get(
    "/unmatched/artwork",
    summary="Get additional-artwork coverage (logo/background/squareart)",
    description="Per-image-type coverage + per-item lists for the Unmatched "
    "page's 'Additional artwork' view, derived from media_asset_matches.",
)
async def get_unmatched_artwork(
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Return per-type artwork stats (applied/missing/needs_review/ignored) and
    the per-type item lists, mirroring the poster unmatched details shape."""
    try:
        logger.debug("Serving GET /api/posters/unmatched/artwork")
        unmatched = UnmatchedAssets(logger=logger.get_adapter("UnmatchedArtwork"))
        stats = unmatched.get_artwork_stats_adhoc()
        return ok(
            "Unmatched artwork coverage retrieved",
            {
                "types": stats.get("types", {}),
                "media": stats.get("media", {}),
                "summary": stats.get("summary", {}),
            },
        )
    except Exception as e:
        logger.error(f"Error retrieving unmatched artwork: {e}")
        return error(
            "Error retrieving unmatched artwork",
            code="UNMATCHED_ARTWORK_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/artwork/{image_type}/ignore",
    summary="Ignore a specific artwork type for a media row",
    description="Mark one (media, image_type) pair as not-needed so it stops "
    "appearing in the Additional-artwork view — independent of other types.",
)
async def ignore_artwork(
    media_id: int,
    image_type: str,
    kind: str = Query("media", pattern="^(media|collection)$"),
    ignored: bool = Query(True),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Toggle the per-(media, image_type) ignore flag in media_asset_matches."""
    if image_type not in ARTWORK_IMAGE_TYPES:
        return error(
            f"image_type must be one of {sorted(ARTWORK_IMAGE_TYPES)}, got '{image_type}'",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/artwork/{image_type}/ignore "
            f"(kind={kind}, ignored={ignored})"
        )
        db.media_asset_matches.set_ignored(kind, media_id, image_type, ignored)
        verb = "ignored" if ignored else "restored"
        return ok(
            f"Artwork {verb}",
            {"id": media_id, "image_type": image_type, "ignored": bool(ignored)},
        )
    except Exception as e:
        logger.error(f"Error updating artwork ignore for {media_id}/{image_type}: {e}")
        return error(
            "Error updating artwork ignore flag",
            code="ARTWORK_IGNORE_ERROR",
            status_code=500,
        )


@router.get(
    "/match/{media_id}/artwork/{image_type}/candidates",
    summary="Candidate artwork files for one (media, image_type)",
    description="Return the title-similar logo/background/squareart files for a "
    "media row, each annotated with whether it would match — powering the manual "
    "artwork picker (the artwork counterpart of the poster candidates endpoint).",
)
async def get_artwork_candidates(
    media_id: int,
    image_type: str,
    kind: str = Query("media", pattern="^(media|collection)$"),
    limit: int = Query(24, ge=1, le=100),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    if image_type not in ARTWORK_IMAGE_TYPES:
        return error(
            f"image_type must be one of {sorted(ARTWORK_IMAGE_TYPES)}, got '{image_type}'",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    try:
        row = (
            db.collection.get_by_id(media_id)
            if kind == "collection"
            else db.media.get_by_id(media_id)
        )
        if not row:
            return error("Media row not found", code="NOT_FOUND", status_code=404)

        asset_type = "collection" if kind == "collection" else row.get("asset_type")
        # Same scoring as the poster picker, scoped to one artwork type.
        candidates = [
            {
                "poster_id": c.get("id"),
                "title": c.get("title"),
                "year": c.get("year"),
                "season_number": c.get("season_number"),
                "style": c.get("style"),
                "image_type": c.get("image_type"),
                "owner": os.path.basename(os.path.dirname(c.get("file") or "")),
                "would_match": matched,
                "similarity": round(sim, 2),
                "reason": reason or "title/year/season did not satisfy the matcher",
            }
            for c, matched, sim, reason in rank_candidates(
                db, row, asset_type, image_type=image_type, limit=limit
            )
        ]

        return ok(
            f"{len(candidates)} candidate {image_type} files",
            {
                "candidates": candidates,
                "media": {
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "season_number": row.get("season_number"),
                    "type": asset_type,
                    "image_type": image_type,
                },
            },
        )
    except Exception as e:
        logger.error(
            f"Error fetching artwork candidates for {media_id}/{image_type}: {e}"
        )
        return error(
            "Error fetching artwork candidates",
            code="ARTWORK_CANDIDATES_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/artwork/{image_type}/apply",
    summary="Manually apply a chosen artwork file to a media row",
    description="Link a specific logo/background/squareart file to one (media, "
    "image_type), apply it (copy to Kometa / upload to Plex), and lock it so a "
    "re-run reuses it. The artwork counterpart of the poster apply endpoint.",
    responses={
        400: {"description": "Unknown image_type, or the file is a different type"},
        404: {"description": "Media row or artwork file not found"},
        500: {"description": "Failed to apply the artwork"},
    },
)
def apply_artwork(
    media_id: int,
    image_type: str,
    poster_id: int = Query(...),
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Link one artwork file to a media/collection row, apply it, and lock it."""
    if image_type not in ARTWORK_IMAGE_TYPES:
        return error(
            f"image_type must be one of {sorted(ARTWORK_IMAGE_TYPES)}, got '{image_type}'",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/artwork/{image_type}/apply "
            f"(poster={poster_id}, kind={kind})"
        )
        row = (
            db.collection.get_by_id(media_id)
            if kind == "collection"
            else db.media.get_by_id(media_id)
        )
        if not row:
            return error("Media row not found", code="NOT_FOUND", status_code=404)
        poster = db.poster.get_by_integer_id(poster_id)
        if not poster:
            return error("Artwork file not found", code="NOT_FOUND", status_code=404)
        poster = dict(poster)
        if (poster.get("image_type") or "poster") != image_type:
            return error(
                f"Chosen file is a '{poster.get('image_type')}', not a '{image_type}'",
                code="IMAGE_TYPE_MISMATCH",
                status_code=400,
            )
        pfile = poster.get("file")
        if not pfile:
            return error("Artwork file has no path", code="NOT_FOUND", status_code=404)

        from backend.modules.asset_renamerr import AssetRenamerr

        target_kind = "collection" if kind == "collection" else "media"
        media = dict(row)
        media["id"] = media_id
        applied, detail = AssetRenamerr(logger=logger).apply_chosen_asset(
            db, target_kind, media, image_type, pfile
        )
        return ok(
            "Artwork applied" if applied else "Artwork saved (apply pending)",
            {
                "id": media_id,
                "image_type": image_type,
                "applied": bool(applied),
                "detail": detail,
            },
        )
    except Exception as e:
        logger.error(f"Error applying artwork for {media_id}/{image_type}: {e}")
        return error(
            "Error applying artwork",
            code="ARTWORK_APPLY_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/artwork/{image_type}/unlock",
    summary="Unlock a manually-picked artwork so the matcher can re-resolve it",
    description="Clear the manual-pick lock on one (media, image_type) so the "
    "next asset run is free to auto-resolve it again. The artwork counterpart of "
    "the poster unlock endpoint.",
)
async def unlock_artwork(
    media_id: int,
    image_type: str,
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    if image_type not in ARTWORK_IMAGE_TYPES:
        return error(
            f"image_type must be one of {sorted(ARTWORK_IMAGE_TYPES)}, got '{image_type}'",
            code="INVALID_IMAGE_TYPE",
            status_code=400,
        )
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/artwork/{image_type}/unlock "
            f"(kind={kind})"
        )
        target_kind = "collection" if kind == "collection" else "media"
        db.media_asset_matches.set_user_confirmed(
            target_kind, media_id, image_type, False
        )
        return ok(
            "Artwork unlocked",
            {"id": media_id, "image_type": image_type, "locked": False},
        )
    except Exception as e:
        logger.error(f"Error unlocking artwork for {media_id}/{image_type}: {e}")
        return error(
            "Error unlocking artwork",
            code="ARTWORK_UNLOCK_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/ignore",
    summary="Dismiss (ignore) a media row from unmatched/review",
    description="Mark a media or collection row as ignored so it stops "
    "appearing in the Unmatched/Needs-Review tabs.",
)
async def ignore_match(
    media_id: int,
    kind: str = Query("media", pattern="^(media|collection)$"),
    ignored: bool = Query(True),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Toggle the ignore flag on a media (default) or collection row."""
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/ignore "
            f"(kind={kind}, ignored={ignored})"
        )
        iface = db.collection if kind == "collection" else db.media
        # set_ignored also releases the manual-pick lock when ignoring, in the
        # same statement, so the matcher is free to re-evaluate the row.
        iface.set_ignored(media_id, ignored)
        verb = "ignored" if ignored else "restored"
        return ok(f"Row {verb}", {"id": media_id, "ignored": bool(ignored)})
    except Exception as e:
        logger.error(f"Error updating ignore flag for {media_id}: {e}")
        return error(
            "Error updating ignore flag",
            code="MATCH_IGNORE_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/approve",
    summary="Approve a needs-review match",
    description="Confirm a needs-review media/collection row, promoting it to "
    "the 'matched' state and clearing any conflict flags.",
    responses={500: {"description": "Failed to approve the match"}},
)
async def approve_match(
    media_id: int,
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Mark a reviewed row as confidently matched."""
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/approve (kind={kind})"
        )
        iface = db.collection if kind == "collection" else db.media
        # approve_match locks the confirmed match in the same statement so a
        # future re-scan can't revert it (Fix B).
        iface.approve_match(media_id)
        return ok("Match approved", {"id": media_id, "match_status": "matched"})
    except Exception as e:
        logger.error(f"Error approving match for {media_id}: {e}")
        return error(
            "Error approving match",
            code="MATCH_APPROVE_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/unlock",
    summary="Unlock a confirmed match and re-open it for review",
    description="Clear the user_confirmed lock on a media/collection row and put "
    "it back into the 'needs_review' queue so the matcher can recompute it (or the "
    "user can re-pick) on the next run.",
    responses={500: {"description": "Failed to unlock the match"}},
)
async def unlock_match(
    media_id: int,
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Release a manual lock and send the row back to Needs Review."""
    try:
        logger.debug(f"Serving POST /api/posters/match/{media_id}/unlock (kind={kind})")
        iface = db.collection if kind == "collection" else db.media
        # reopen_for_review drops the lock in the same statement, so the next
        # scheduled run is free to recompute the match.
        iface.reopen_for_review(media_id)
        return ok(
            "Match unlocked",
            {"id": media_id, "match_status": "needs_review"},
        )
    except Exception as e:
        logger.error(f"Error unlocking match for {media_id}: {e}")
        return error(
            "Error unlocking match",
            code="MATCH_UNLOCK_ERROR",
            status_code=500,
        )


@router.get(
    "/match/{media_id}/candidates",
    summary="Candidate posters for a media row (picker + why-no-match)",
    description="Return the title-similar posters of the right type/season for "
    "a media/collection row, each annotated with whether it would match and "
    "why — powering both the manual poster picker and match diagnostics.",
)
async def get_match_candidates(
    media_id: int,
    kind: str = Query("media", pattern="^(media|collection)$"),
    limit: int = Query(24, ge=1, le=100),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        row = (
            db.collection.get_by_id(media_id)
            if kind == "collection"
            else db.media.get_by_id(media_id)
        )
        if not row:
            return error("Media row not found", code="NOT_FOUND", status_code=404)

        asset_type = "collection" if kind == "collection" else row.get("asset_type")
        candidates = [
            {
                "poster_id": c.get("id"),
                "title": c.get("title"),
                "year": c.get("year"),
                "season_number": c.get("season_number"),
                "style": c.get("style"),
                "owner": os.path.basename(os.path.dirname(c.get("file") or "")),
                "would_match": matched,
                "similarity": round(sim, 2),
                "reason": reason or "title/year/season did not satisfy the matcher",
            }
            for c, matched, sim, reason in rank_candidates(
                db, row, asset_type, limit=limit
            )
        ]

        return ok(
            f"{len(candidates)} candidate posters",
            {
                "candidates": candidates,
                "media": {
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "season_number": row.get("season_number"),
                    "type": asset_type,
                },
            },
        )
    except Exception as e:
        logger.error(f"Error fetching match candidates for {media_id}: {e}")
        return error(
            "Error fetching candidates",
            code="MATCH_CANDIDATES_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/apply",
    summary="Manually apply a chosen poster to a media row",
    description="Link a specific poster to a media/collection row and copy it "
    "to the destination. Used by the manual poster picker.",
    responses={
        404: {"description": "Media row or poster not found"},
        500: {"description": "Failed to apply the poster"},
    },
)
def apply_match(
    media_id: int,
    poster_id: int = Query(...),
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Link one poster to a media/collection row and apply it to the destination."""
    try:
        logger.debug(
            f"Serving POST /api/posters/match/{media_id}/apply (poster={poster_id})"
        )
        row = (
            db.collection.get_by_id(media_id)
            if kind == "collection"
            else db.media.get_by_id(media_id)
        )
        if not row:
            return error("Media row not found", code="NOT_FOUND", status_code=404)
        poster = db.poster.get_by_integer_id(poster_id)
        if not poster:
            return error("Poster not found", code="NOT_FOUND", status_code=404)

        pfile = poster.get("file")
        # Without this the row locks as matched with no source file, and every
        # later run skips it (mirrors apply_artwork's guard).
        if not pfile:
            return error("Poster file has no path", code="NOT_FOUND", status_code=404)
        now = datetime.datetime.now().isoformat(timespec="seconds")

        if kind == "collection":
            db.collection.update(
                title=row.get("title"),
                year=row.get("year"),
                library_name=row.get("library_name"),
                instance_name=row.get("instance_name"),
                matched_value=True,
                original_file=pfile,
                match_status="matched",
                match_confidence=1.0,
                match_reason="Manually applied",
                conflict_ids="[]",
                id=media_id,
            )
            db.collection.set_ignored(media_id, False)
            db.collection.set_match_provenance(media_id, now, pfile)
            db.collection.set_user_confirmed(media_id, True)
        else:
            db.media.update(
                asset_type=row.get("asset_type"),
                title=row.get("title"),
                year=row.get("year"),
                instance_name=row.get("instance_name"),
                matched_value=True,
                season_number=row.get("season_number"),
                original_file=pfile,
                match_status="matched",
                match_confidence=1.0,
                match_reason="Manually applied",
                conflict_ids="[]",
                id=media_id,
            )
            db.media.set_ignored(media_id, False)
            db.media.set_match_provenance(media_id, now, pfile)
            db.media.set_user_confirmed(media_id, True)

        # Apply this one poster immediately, the same way a full run would: copy
        # it to the Kometa destination (rename_file → renamed_file) AND push it
        # to Plex for just this row (single-item manifest, force=True). Reuse the
        # cached Plex snapshot (refresh_plex=False) so the click stays fast. The
        # match is already saved + locked above, so if neither leg succeeds the
        # poster still applies (without reverting) on the next poster_renamerr run.
        copied = False
        plex_ok = False
        item = dict(row)
        item["original_file"] = pfile
        item["id"] = media_id
        from backend.modules.poster_renamerr import PosterRenamerr

        renamer = PosterRenamerr(logger=logger)
        # Honour the module's apply_method (strict either/or): "kometa" copies
        # the poster into the destination dir; "plex" stages it (apply_staging)
        # and uploads straight to Plex for opted-in instances, keeping nothing
        # on disk. The match is already saved + locked above, so if the chosen
        # leg fails the poster still applies on the next poster_renamerr run.
        apply_method = getattr(renamer.config, "apply_method", "kometa")
        manifest = (
            {"collections_cache": [media_id]}
            if kind == "collection"
            else {"media_cache": [media_id]}
        )
        with renamer.apply_staging():
            try:
                renamer.rename_file(item, db)
                renamed = item.get("renamed_file")
                staged = bool(renamed and os.path.lexists(renamed))
            except Exception as exc:
                staged = False
                logger.warning(f"apply: rename/stage failed ({exc})")

            if apply_method == "plex":
                try:
                    from backend.util.upload_posters import PosterUploader

                    up = PosterUploader(
                        db=db,
                        logger=logger,
                        manifest=manifest,
                        force=True,
                        refresh_plex=False,
                    ).run()
                    plex_ok = bool(up.get("success"))
                except Exception as exc:
                    logger.warning(f"apply: Plex upload failed ({exc})")
            else:
                # kometa: the staged copy IS the destination file (no upload).
                copied = staged

        applied = plex_ok or copied
        if plex_ok:
            message = "Poster applied to Plex"
        elif copied:
            message = "Poster copied to assets directory (Kometa will apply)"
        else:
            message = (
                "Match saved and locked — it will be applied on the next "
                "poster_renamerr run"
            )

        return ok(
            message,
            {
                "id": media_id,
                "poster_id": poster_id,
                "applied": applied,
                "plex": plex_ok,
                "copied": copied,
            },
        )
    except Exception as e:
        logger.error(f"Error applying poster {poster_id} to {media_id}: {e}")
        return error(
            "Error applying poster",
            code="MATCH_APPLY_ERROR",
            status_code=500,
        )
