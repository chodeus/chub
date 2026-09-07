"""Poster file operations: analyze, preview, targeted upload, dimension backfill."""

import os
from typing import Any

from fastapi import Depends
from fastapi.responses import FileResponse, JSONResponse

from backend.api.posters._shared import router
from backend.api.utils import (
    error,
    get_database,
    get_logger,
    ok,
    worker_error,
)
from backend.util.config import ConfigError
from backend.util.database import ChubDB


@router.get(
    "/analyze",
    summary="Analyze poster directory",
    description="Analyze a directory for poster files and return statistics.",
    responses={
        200: {
            "description": "Directory analysis completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Analyzed location '/path/to/posters' - found 150 files",
                        "data": {
                            "file_count": 150,
                            "size_bytes": 52428800,
                            "files": ["movie1-poster.jpg", "movie2-poster.png"],
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid location or location parameter missing"},
    },
)
def analyze_poster_directory(
    location: str = None, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Analyze a directory for poster files and statistics.

    Recursively scans the specified directory to count files,
    calculate total size, and generate a file listing. Excludes
    temporary files and provides detailed analysis for management.

    Args:
        location: Directory path to analyze for poster files

    Returns:
        Directory analysis with file count, size, and file listing
    """
    try:
        logger.debug(f"Serving GET /api/posters/analyze for location: {location}")

        # Load config once — needed for default location + allow-list check
        from backend.util.config import load_config
        from backend.util.path_safety import is_path_allowed

        try:
            config = load_config()
        except ConfigError:
            raise
        except Exception:  # noqa: S110 — config may not be loaded at boot
            config = None

        if not location:
            # Default to poster destination from config
            if config is not None:
                location = getattr(config.poster_renamerr, "destination_dir", None)
            if not location:
                return error(
                    "Location parameter is required and no default destination configured",
                    code="LOCATION_REQUIRED",
                    status_code=400,
                )

        # Restrict to configured allowed roots. Fail closed if config is
        # unavailable — otherwise the allow-list check is skipped entirely.
        if config is None:
            return error(
                "Configuration unavailable — cannot verify allowed directories",
                code="CONFIG_UNAVAILABLE",
                status_code=503,
            )
        if not is_path_allowed(location, config):
            return error(
                "Access denied — path outside allowed directories",
                code="PATH_NOT_ALLOWED",
                status_code=403,
            )

        if not os.path.isdir(location):
            return error(
                f"Invalid location: '{location}' is not a directory",
                code="INVALID_LOCATION",
                status_code=400,
            )

        total_size = 0
        poster_files = []

        for root, dirs, files in os.walk(location):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    stat = os.stat(fp)
                    total_size += stat.st_size
                    rel_path = os.path.relpath(fp, location)

                    # Skip temporary files
                    if rel_path.startswith("tmp" + os.sep) or rel_path.startswith(
                        "tmp/"
                    ):
                        continue

                    poster_files.append(rel_path)
                except Exception as e:
                    logger.error(f"Skipped file {fp}: {e}")
                    continue

        return ok(
            f"Analyzed location '{location}' - found {len(poster_files)} files",
            {
                "file_count": len(poster_files),
                "size_bytes": total_size,
                "files": sorted(poster_files),
            },
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error analyzing poster location: {e}")
        return error(
            "Error analyzing poster location",
            code="POSTER_ANALYSIS_ERROR",
            status_code=500,
        )


@router.get(
    "/preview",
    summary="Preview poster file",
    description="Return a poster image file for preview with security validation.",
    responses={
        200: {
            "description": "Poster file served successfully",
            "content": {"image/*": {"example": "Binary image data"}},
        },
        400: {"description": "Missing file path parameters"},
        403: {"description": "Access denied - path outside allowed directory"},
        404: {"description": "Poster file not found"},
        415: {"description": "Unsupported file type"},
    },
)
def preview_poster_file(
    location: str = "", path: str = "", logger: Any = Depends(get_logger)
) -> FileResponse:
    """
    Return a poster image file for preview.

    Supports both absolute paths and location + relative path combinations.
    Includes comprehensive security checks to prevent directory traversal
    attacks and validates file types.

    Args:
        location: Base directory path (optional if using absolute path)
        path: File path (can be absolute or relative to location)

    Returns:
        Image file response for browser display
    """
    try:
        logger.debug(
            f"Serving GET /api/posters/preview for location: {location}, path: {path}"
        )

        if not location or not path:
            return error(
                "Both location and path parameters are required",
                code="MISSING_FILE_PATH",
                status_code=400,
            )

        # Reject null bytes anywhere (path-injection vector)
        if "\x00" in location or "\x00" in path:
            return error(
                "Invalid path",
                code="INVALID_PATH",
                status_code=400,
            )

        # Restrict the served file to configured allowed roots — otherwise
        # an authenticated caller could point at arbitrary dirs (/etc, /root).
        from backend.util.config import load_config
        from backend.util.path_safety import resolve_under_root

        try:
            config = load_config()
        except ConfigError:
            raise
        except Exception:  # noqa: S110 — fail closed below
            config = None

        # Fail closed: without config there are no allowed roots to check against.
        file_path = resolve_under_root(location, path, config) if config else None
        if file_path is None:
            return error(
                "Access denied - path outside allowed directory",
                code="PATH_TRAVERSAL_DENIED",
                status_code=403,
            )

        if not file_path.exists() or not file_path.is_file():
            return error(
                "Poster file not found",
                code="POSTER_FILE_NOT_FOUND",
                status_code=404,
            )

        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        if file_path.suffix.lower() not in allowed_extensions:
            return error(
                f"Unsupported file type: {file_path.suffix}",
                code="UNSUPPORTED_FILE_TYPE",
                status_code=415,
            )

        return FileResponse(str(file_path))

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error serving poster preview: {e}")
        return error(
            "Error serving poster preview",
            code="POSTER_PREVIEW_ERROR",
            status_code=500,
        )


@router.post(
    "/upload/media/{media_id}",
    summary="Upload posters for media item",
    description="Trigger poster upload operation for a specific media cache item.",
    responses={
        200: {
            "description": "Upload triggered successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Upload triggered for media cache item 123",
                        "data": {"uploaded": 1, "skipped": 0},
                    }
                }
            },
        }
    },
)
def upload_media_posters(
    media_id: int, logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> JSONResponse:
    """
    Trigger poster upload for a specific media cache item.

    Forces upload of posters for the specified media cache entry
    using the poster uploader system. Useful for manual poster
    management and troubleshooting upload issues.

    Args:
        media_id: The media cache item ID to upload posters for

    Returns:
        Upload operation results with success/failure counts
    """
    try:
        logger.debug(f"Serving POST /api/posters/upload/media/{media_id}")

        manifest = {"media_cache": [media_id]}

        from backend.util.upload_posters import PosterUploader

        result = PosterUploader(
            db=db, logger=logger, manifest=manifest, force=True
        ).run()

        if result.get("success"):
            return ok(
                f"Upload triggered for media cache item {media_id}",
                result.get("data", {}),
            )
        else:
            return worker_error(
                result,
                logger,
                f"Upload failed for media cache item {media_id}",
                "MEDIA_UPLOAD_FAILED",
            )

    except Exception as e:
        logger.error(f"Error uploading media cache item {media_id}: {e}")
        return error(
            "Error triggering upload",
            code="MEDIA_UPLOAD_ERROR",
            status_code=500,
        )


@router.post(
    "/upload/collection/{collection_id}",
    summary="Upload posters for collection item",
    description="Trigger poster upload operation for a specific collection cache item.",
    responses={
        200: {
            "description": "Upload triggered successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Upload triggered for collection cache item 123",
                        "data": {"uploaded": 1, "skipped": 0},
                    }
                }
            },
        }
    },
)
def upload_collection_posters(
    collection_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Trigger poster upload for a specific collection cache item.

    Forces upload of posters for the specified collection cache entry
    using the poster uploader system. Useful for manual poster
    management and collection artwork updates.

    Args:
        collection_id: The collection cache item ID to upload posters for

    Returns:
        Upload operation results with success/failure counts
    """
    try:
        logger.debug(f"Serving POST /api/posters/upload/collection/{collection_id}")

        manifest = {"collections_cache": [collection_id]}

        from backend.util.upload_posters import PosterUploader

        result = PosterUploader(
            db=db, logger=logger, manifest=manifest, force=True
        ).run()

        if result.get("success"):
            return ok(
                f"Upload triggered for collection cache item {collection_id}",
                result.get("data", {}),
            )
        else:
            return worker_error(
                result,
                logger,
                f"Upload failed for collection cache item {collection_id}",
                "COLLECTION_UPLOAD_FAILED",
            )

    except Exception as e:
        logger.error(f"Error uploading collection cache item {collection_id}: {e}")
        return error(
            "Error triggering upload",
            code="COLLECTION_UPLOAD_ERROR",
            status_code=500,
        )


# --- Named-path poster endpoints (must precede /{poster_id} catch-all) ---


@router.post(
    "/backfill-dimensions",
    summary="Backfill poster width/height",
    description="Walk poster_cache rows missing width/height and populate "
    "them by opening the file with PIL. Processes up to `limit` rows per call "
    "so it can be run incrementally.",
    responses={500: {"description": "Failed to backfill poster dimensions"}},
)
def backfill_poster_dimensions(
    limit: int = 200,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Populate missing poster width/height for up to `limit` rows."""
    # Sync on purpose: the PIL/db loop blocks, so Starlette runs the whole
    # endpoint in a threadpool instead of stalling the event loop.
    try:
        limit = max(1, min(limit, 2000))
        rows = db.poster.find_missing_dimensions(limit)

        from PIL import Image

        from backend.util.config import load_config
        from backend.util.path_safety import resolve_confined

        # poster_cache.file is persisted data, not a trust boundary — confine
        # every row before PIL opens it.
        config = load_config()
        updated = 0
        skipped = 0
        for r in rows:
            path = resolve_confined(r["file"], config)
            if path is None:
                logger.debug(f"Skipping poster_id={r['id']}: outside allowed roots")
                skipped += 1
                continue
            if not path.is_file():
                skipped += 1
                continue
            try:
                with Image.open(path) as img:
                    w, h = img.size
                db.poster.record_dimensions(r["id"], w, h)
                updated += 1
            except Exception as img_err:
                logger.debug(f"Skipping poster_id={r['id']}: {img_err}")
                skipped += 1

        return ok(
            f"Backfilled {updated} poster dimensions ({skipped} skipped)",
            {"updated": updated, "skipped": skipped, "batch_size": limit},
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error backfilling poster dimensions: {e}")
        return error(
            "Error backfilling poster dimensions",
            code="BACKFILL_DIMENSIONS_ERROR",
            status_code=500,
        )
