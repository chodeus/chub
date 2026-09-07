"""Single-poster endpoints under the `/{poster_id}` catch-all family."""

import os
from typing import Any, Optional

from fastapi import Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from backend.api.posters._shared import router
from backend.api.utils import (
    BODY_TOO_LARGE,
    body_too_large_error,
    error,
    get_database,
    get_logger,
    ok,
    read_json_object,
)
from backend.util.config import ConfigError
from backend.util.database import ChubDB
from backend.util.poster_images import (
    build_thumbnail,
    transcode_poster,
)


@router.get(
    "/{poster_id}",
    summary="Get poster details",
    description="Retrieve detailed information about a specific poster by ID.",
    responses={
        200: {
            "description": "Poster details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster retrieved",
                        "data": {
                            "id": 1,
                            "title": "The Matrix",
                            "year": 1999,
                            "file": "The Matrix (1999).jpg",
                        },
                    }
                }
            },
        },
        404: {"description": "Poster not found"},
    },
)
def get_poster(
    poster_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get a single poster by its unique ID.

    Returns the complete poster record including file path,
    metadata, and match status information.

    Args:
        poster_id: The unique identifier of the poster

    Returns:
        Complete poster details
    """
    try:
        logger.debug(f"Serving GET /api/posters/{poster_id}")
        poster = db.poster.get_by_integer_id(poster_id)
        if not poster:
            return error("Poster not found", code="POSTER_NOT_FOUND", status_code=404)
        return ok("Poster retrieved", poster)
    except Exception as e:
        logger.error(f"Error retrieving poster {poster_id}: {e}")
        return error(
            "Error retrieving poster",
            code="POSTER_GET_ERROR",
            status_code=500,
        )


@router.get(
    "/{poster_id}/thumbnail",
    summary="Get poster thumbnail",
    description="Get a downsized thumbnail version of a poster for grid views.",
    responses={
        200: {
            "description": "Thumbnail image served successfully",
            "content": {"image/jpeg": {"example": "Binary image data"}},
        },
        403: {"description": "Access denied - path outside allowed directory"},
        404: {"description": "Poster or file not found"},
    },
)
def get_poster_thumbnail(
    poster_id: int,
    width: int = Query(200, ge=50, le=500, description="Thumbnail width in pixels"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Any:
    """
    Get a cached thumbnail of a poster image.

    Generates a downsized JPEG thumbnail on first request and caches it
    in a .thumbnails subdirectory. Subsequent requests serve from cache.

    Sync on purpose: the LANCZOS resize + JPEG encode are blocking, so
    Starlette runs this in a threadpool instead of stalling the event loop.

    Args:
        poster_id: The unique identifier of the poster
        width: Target thumbnail width (height scales proportionally)

    Returns:
        Thumbnail image file response
    """
    try:
        poster = db.poster.get_by_integer_id(poster_id)
        if not poster:
            return error("Poster not found", code="POSTER_NOT_FOUND", status_code=404)

        file_path = poster.get("file", "")
        folder = poster.get("folder", "")
        raw_path = os.path.join(folder, file_path) if folder else file_path

        if not raw_path:
            return error(
                "Poster file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        # Confine the served path to configured roots — realpath normalizes
        # but authorizes nothing, so a poisoned row could point anywhere.
        from backend.util.config import load_config
        from backend.util.path_safety import resolve_confined

        try:
            config = load_config()
        except ConfigError:
            raise
        except Exception:  # noqa: S110 — fail closed below
            config = None

        real = resolve_confined(raw_path, config) if config is not None else None
        if real is None:
            return error(
                "Access denied - path outside allowed directory",
                code="PATH_TRAVERSAL_DENIED",
                status_code=403,
            )
        full_path = str(real)
        if not os.path.isfile(full_path):
            return error(
                "Poster file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        return FileResponse(
            build_thumbnail(full_path, poster_id, width), media_type="image/jpeg"
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error generating thumbnail for poster {poster_id}: {e}")
        return error(
            "Error generating thumbnail",
            code="THUMBNAIL_ERROR",
            status_code=500,
        )


@router.post(
    "/{poster_id}/download",
    summary="Download poster file",
    description="Download a poster image file, optionally resized or converted.",
    responses={
        200: {
            "description": "Poster file served successfully",
            "content": {"image/*": {"example": "Binary image data"}},
        },
        403: {"description": "Access denied - path outside allowed directory"},
        404: {"description": "Poster or file not found"},
    },
)
def download_poster(
    poster_id: int,
    size: Optional[int] = Query(
        None, ge=100, le=4000, description="Max dimension in pixels"
    ),
    format: Optional[str] = Query(None, description="Target format: jpeg, webp, png"),
    quality: Optional[int] = Query(
        None, ge=1, le=100, description="Compression quality"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Any:
    """
    Download a poster file, optionally with image processing.

    When no processing params are provided, serves the raw file.
    When size, format, or quality are specified, processes the image
    before serving.

    Sync on purpose: the optional resize/encode is blocking, so Starlette
    runs this in a threadpool instead of stalling the event loop.

    Args:
        poster_id: The unique identifier of the poster to download
        size: Optional max dimension for resize
        format: Optional target format (jpeg, webp, png)
        quality: Optional compression quality (1-100)

    Returns:
        Image file response for download
    """
    try:
        logger.debug(f"Serving POST /api/posters/{poster_id}/download")
        poster = db.poster.get_by_integer_id(poster_id)
        if not poster:
            return error("Poster not found", code="POSTER_NOT_FOUND", status_code=404)

        file_path = poster.get("file")
        folder = poster.get("folder")
        if folder and file_path:
            raw_path = os.path.join(folder, file_path)
        elif file_path:
            raw_path = file_path
        else:
            return error(
                "No file path for poster", code="NO_FILE_PATH", status_code=404
            )

        # Confine the served path to configured roots — realpath normalizes
        # but authorizes nothing, so a poisoned row could point anywhere.
        from backend.util.config import load_config
        from backend.util.path_safety import resolve_confined

        try:
            config = load_config()
        except ConfigError:
            raise
        except Exception:  # noqa: S110 — fail closed below
            config = None

        real = resolve_confined(raw_path, config) if config is not None else None
        if real is None:
            return error(
                "Access denied - path outside allowed directory",
                code="PATH_TRAVERSAL_DENIED",
                status_code=403,
            )
        full_path = str(real)

        if not os.path.exists(full_path):
            return error(
                "Poster file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        # No processing requested — serve raw file
        if size is None and format is None and quality is None:
            return FileResponse(full_path)

        # Process the image before serving
        tmp_path, media_type, target_ext = transcode_poster(
            full_path, size=size, image_format=format, quality=quality
        )

        return FileResponse(
            tmp_path,
            media_type=media_type,
            filename=f"poster_{poster_id}{target_ext}",
            # FileResponse doesn't delete what it serves — clean up the temp file.
            background=BackgroundTask(os.unlink, tmp_path),
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error downloading poster {poster_id}: {e}")
        return error(
            "Error downloading poster",
            code="POSTER_DOWNLOAD_ERROR",
            status_code=500,
        )


@router.delete(
    "/{poster_id}",
    summary="Delete poster",
    description="Delete a poster from the cache and optionally from disk.",
    responses={
        200: {
            "description": "Poster deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster 123 deleted",
                        "data": {
                            "deleted_id": 123,
                            "file_deleted": False,
                            "media_unmatched": 1,
                        },
                    }
                }
            },
        },
        404: {"description": "Poster not found"},
        413: {"description": "Request body too large"},
        500: {"description": "Malformed config, or the delete failed"},
    },
)
async def delete_poster(
    poster_id: int,
    request: Request,
    delete_file: bool = Query(False, description="Also delete the file from disk"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Delete a poster from the cache and optionally from disk.

    Removes the poster record from the database, optionally deletes
    the physical file, and marks any media items that were applied
    from that file as unmatched.

    The deleteFile flag can be provided via JSON request body
    or as a query parameter (body takes precedence).

    Args:
        poster_id: The unique identifier of the poster to delete
        request: HTTP request for reading optional JSON body
        delete_file: Whether to also delete the file from disk

    Returns:
        Deletion result with file and media unmatching details
    """
    try:
        logger.debug(f"Serving DELETE /api/posters/{poster_id}")

        # Read deleteFile from JSON body if provided, fall back to query param
        body = await read_json_object(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        delete_file = body.get("deleteFile", delete_file)

        # Authorize BEFORE the irreversible row delete: a malformed config must
        # abort the whole request, not leave the row gone and the file orphaned.
        config = None
        if delete_file:
            from backend.util.config import load_config

            config = load_config()

        record = db.poster.delete_by_integer_id(poster_id)
        if not record:
            return error("Poster not found", code="POSTER_NOT_FOUND", status_code=404)

        # Optionally delete file from disk
        file_path = record.get("file")
        folder = record.get("folder")
        full_path = (
            os.path.join(folder, file_path) if folder and file_path else file_path
        )
        # A poisoned row must never reach os.remove: resolve first, then require
        # membership in a configured root.
        file_deleted = False
        if delete_file and full_path:
            from backend.util.path_safety import resolve_confined

            real = resolve_confined(full_path, config)
            if real is None or str(real) == os.path.realpath(os.sep):
                logger.error(
                    f"Refusing to delete poster file outside roots: {full_path}"
                )
            elif real.exists():
                os.remove(real)
                file_deleted = True
                logger.info(f"Deleted poster file: {real}")

        # Mark associated media items as unmatched
        unmatched_count = 0
        poster_title = record.get("normalized_title")
        if poster_title:
            try:
                # Find media items that were matched to this poster by original_file
                if full_path:
                    media_items = db.media.find_by_original_file_basename(
                        os.path.basename(full_path)
                    )
                    for item in media_items:
                        db.media.update(
                            asset_type=item["asset_type"],
                            title=item["title"],
                            year=item["year"],
                            instance_name=item["instance_name"],
                            season_number=item.get("season_number"),
                            matched_value=0,
                            original_file="",
                            renamed_file="",
                        )
                        unmatched_count += 1
            except Exception as unmatched_err:
                logger.debug(f"Could not update unmatched media: {unmatched_err}")

        return ok(
            f"Poster {poster_id} deleted",
            {
                "deleted_id": poster_id,
                "file_deleted": file_deleted,
                "media_unmatched": unmatched_count,
            },
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error deleting poster {poster_id}: {e}")
        return error(
            "Error deleting poster",
            code="POSTER_DELETE_ERROR",
            status_code=500,
        )
