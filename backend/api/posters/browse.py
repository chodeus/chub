"""Poster browse, bulk auto-match, and single-file upload endpoints."""

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse

from backend.api.posters._shared import router
from backend.api.utils import (
    error,
    get_database,
    get_logger,
    ok,
)
from backend.util.config import ConfigError
from backend.util.database import ChubDB


@router.post(
    "/auto-match",
    summary="Auto-match posters to media",
    description="Trigger automatic poster-to-media matching by enqueuing a background job.",
    responses={
        200: {
            "description": "Auto-match job initiated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Auto-match initiated",
                        "data": {"job_id": 123},
                    }
                }
            },
        }
    },
)
def auto_match_posters(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Trigger automatic poster-to-media matching.

    Enqueues a background job that runs the poster matching
    algorithm to associate unmatched posters with media items
    in the library.

    Returns:
        Job ID for tracking the auto-match operation
    """
    try:
        logger.debug("Serving POST /api/posters/auto-match")
        result = db.worker.enqueue_job(
            "jobs", {"module_name": "poster_renamerr"}, job_type="module_run"
        )
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok("Auto-match initiated", {"job_id": job_id})
        return error(
            "Error enqueuing auto-match", code="AUTO_MATCH_ERROR", status_code=500
        )
    except Exception as e:
        logger.error(f"Error initiating auto-match: {e}")
        return error(
            "Error initiating auto-match",
            code="AUTO_MATCH_ERROR",
            status_code=500,
        )


@router.get(
    "/browse",
    summary="Browse cached posters with filtering",
    description="Browse cached poster files with optional owner, type, and search filters.",
    responses={
        200: {
            "description": "Filtered poster listing retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 60 of 500 posters",
                        "data": {
                            "items": [{"id": 1, "title": "The Matrix"}],
                            "total": 500,
                            "owners": ["Sahara", "Stupifier"],
                        },
                    }
                }
            },
        }
    },
)
def browse_posters(
    owner: Optional[str] = Query(None, description="Filter by GDrive owner name"),
    type: Optional[str] = Query(
        None, description="Filter by asset type: movie, show, season, collection"
    ),
    query: Optional[str] = Query(None, description="Search by title"),
    style: Optional[str] = Query(
        None,
        description="Filter by poster style (e.g. CL2K, MM2K). Use 'other' for rows whose source dir didn't match a configured gdrive entry.",
    ),
    image_type: Optional[str] = Query(
        None,
        description="Image type to browse: poster (default), logo, background, squareart, banner, or 'artwork' for the logo+squareart+background set.",
    ),
    limit: int = Query(
        60, ge=0, le=200, description="Results per page (0 for owners only)"
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Browse cached poster files with optional filtering and pagination.

    Args:
        owner: Filter by GDrive owner (derived from folder path)
        type: Filter by asset type (movie, show, season, collection)
        query: Search by title
        style: Filter by poster style (CL2K, MM2K, or 'other' for unclassified)
        limit: Results per page
        offset: Pagination offset

    Returns:
        Paginated poster list with available owner and style values for filtering
    """
    try:
        logger.debug("Serving GET /api/posters/browse")
        # Default to posters; clamp anything unrecognised so the param can't be
        # used to inject an arbitrary image_type value into the query.
        allowed_image_types = {
            "poster",
            "logo",
            "background",
            "squareart",
            "banner",
            "artwork",
        }
        safe_image_type = image_type if image_type in allowed_image_types else "poster"
        result = db.poster.browse(
            owner=owner,
            asset_type=type,
            query=query,
            style=style,
            limit=limit,
            offset=offset,
            image_type=safe_image_type,
        )
        # Owner/Style are independent of the Image filter: list EVERY location
        # (image_type=None) so an owner like a logos-only "Extras" drive is
        # selectable regardless of which image type is being browsed.
        result["owners"] = db.poster.get_distinct_owners(image_type=None)
        # Merge styles already stamped on rows with styles derivable from the
        # current gdrive_list config so the dropdown is useful even before
        # poster_renamerr has re-upserted existing rows with the new column.
        db_styles = set(db.poster.get_distinct_styles(image_type=None))
        configured_styles = set()
        try:
            from backend.util.config import load_config

            config = load_config()
            sync_cfg = getattr(config, "sync_gdrive", None)
            for entry in getattr(sync_cfg, "gdrive_list", None) or []:
                name = (getattr(entry, "name", "") or "").strip()
                if name:
                    head = name.split(None, 1)[0]
                    if head:
                        configured_styles.add(head)
        except ConfigError:
            raise
        except Exception as e:
            logger.debug(f"Could not derive configured styles from config: {e}")
        result["styles"] = sorted(db_styles | configured_styles)
        return ok(
            f"Retrieved {len(result['items'])} of {result['total']} posters", result
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error browsing posters: {e}")
        return error(
            "Error browsing posters",
            code="POSTER_BROWSE_ERROR",
            status_code=500,
        )


@router.post(
    "/upload",
    summary="Upload a poster file",
    description="Upload a poster image file and store it in the configured poster directory.",
    responses={
        200: {
            "description": "Poster uploaded successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster uploaded successfully",
                        "data": {
                            "filename": "Movie Name (2024).jpg",
                            "path": "/posters/Movie Name (2024).jpg",
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid file type or missing file"},
    },
)
async def upload_poster(
    file: UploadFile = File(..., description="Poster image file"),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Upload a poster image file.

    Accepts an image file (jpg, jpeg, png, webp) and stores it
    in the poster destination directory configured in poster_renamerr.

    Args:
        file: The poster image file to upload

    Returns:
        Upload confirmation with filename and storage path
    """
    # Max 20 MiB — posters are typically 100-500 KiB; anything larger is
    # almost certainly wrong (or a disk-fill attempt).
    MAX_UPLOAD_BYTES = 20 * 1024 * 1024
    # First bytes that identify a real image. We check the magic even though
    # we already check the extension, because an attacker can rename anything
    # to `.jpg`.
    IMAGE_MAGIC = (
        b"\xff\xd8\xff",  # JPEG
        b"\x89PNG\r\n\x1a\n",  # PNG
        b"RIFF",  # WEBP (followed by 4-byte size + "WEBP")
    )

    try:
        logger.debug(f"Serving POST /api/posters/upload filename={file.filename}")

        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        ext = Path(file.filename).suffix.lower() if file.filename else ""
        if ext not in allowed_extensions:
            return error(
                f"Unsupported file type: {ext}. Allowed: {', '.join(allowed_extensions)}",
                code="UNSUPPORTED_FILE_TYPE",
                status_code=400,
            )

        # Read one byte over the cap so we can detect oversize without
        # trusting the Content-Length header.
        contents = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(contents) > MAX_UPLOAD_BYTES:
            return error(
                f"File exceeds max upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB",
                code="FILE_TOO_LARGE",
                status_code=413,
            )

        head = contents[:12]
        is_image = any(head.startswith(magic) for magic in IMAGE_MAGIC) or (
            ext == ".webp" and head.startswith(b"RIFF") and head[8:12] == b"WEBP"
        )
        if not is_image:
            return error(
                "Uploaded file is not a valid image (magic bytes mismatch)",
                code="INVALID_IMAGE",
                status_code=400,
            )

        from backend.util.config import load_config

        config = load_config()
        dest_dir = getattr(config.poster_renamerr, "destination_dir", None)
        if not dest_dir:
            return error(
                "No poster destination directory configured",
                code="NO_DESTINATION_DIR",
                status_code=400,
            )

        os.makedirs(dest_dir, exist_ok=True)

        # Sanitize filename
        safe_name = Path(file.filename).name
        dest_path = os.path.join(dest_dir, safe_name)

        with open(dest_path, "wb") as f:
            f.write(contents)

        logger.info(f"Poster uploaded: {dest_path}")
        return ok(
            "Poster uploaded successfully",
            {"filename": safe_name, "path": dest_path, "size_bytes": len(contents)},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error uploading poster: {e}")
        return error(
            "Error uploading poster",
            code="POSTER_UPLOAD_ERROR",
            status_code=500,
        )
