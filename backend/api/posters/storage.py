"""Poster storage endpoints: optimization and on-disk file listing."""

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

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
from backend.util.helper import get_static_dir
from backend.util.poster_images import (
    optimize_poster_files,
    resolve_format,
)


@router.post(
    "/optimize",
    summary="Optimize poster storage",
    description="Optimize poster storage by compressing, resizing, and converting poster files.",
    responses={
        200: {
            "description": "Optimization result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Optimized 42 posters, saved 128.5 MB",
                        "data": {
                            "processed": 42,
                            "skipped": 10,
                            "failed": 0,
                            "bytes_saved": 134742016,
                            "mode": "optimize",
                        },
                    }
                }
            },
        },
        400: {"description": "Unknown optimize mode"},
    },
)
async def optimize_posters(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Optimize poster storage.

    Resizes oversized posters, converts to target format, and applies
    quality compression. Supports 'report' mode for dry runs.

    Request body (JSON):
        max_width: Maximum width in pixels (default 1000)
        max_height: Maximum height in pixels (default 1500)
        format: Target format - 'jpeg', 'webp', or 'png' (default 'jpeg')
        quality: Compression quality 1-100 (default 85)
        mode: 'optimize' to process, 'report' for dry run (default 'report')

    Returns:
        Optimization results with space savings details
    """
    body = await read_json_object(request)
    if body is BODY_TOO_LARGE:
        return body_too_large_error()

    max_width = body.get("max_width", 1000)
    max_height = body.get("max_height", 1500)
    target_format = body.get("format", "jpeg").lower()
    quality = max(1, min(100, body.get("quality", 85)))
    raw_mode = body.get("mode", "report")
    mode = raw_mode.lower() if isinstance(raw_mode, str) else raw_mode
    # optimize_poster_files only dry-runs on "report" — every other value takes
    # the shutil.move/os.remove branch, so an unknown mode must stop here.
    if mode not in ("report", "optimize"):
        return error("Invalid optimize mode", code="INVALID_MODE", status_code=400)

    pil_format, target_ext = resolve_format(target_format)

    # The full-cache read + per-poster PIL resize/convert loop is heavy and
    # CPU-bound; run it off the event loop so it doesn't freeze the server.
    try:
        from backend.util.config import load_config

        # Loaded once here so the loop confines every cache row it rewrites.
        config = load_config()
        message, data = await run_in_threadpool(
            optimize_poster_files,
            db,
            logger,
            config,
            max_width,
            max_height,
            pil_format,
            target_ext,
            quality,
            mode,
        )
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error optimizing posters: {e}", exc_info=True)
        return error(
            "Error optimizing posters",
            code="OPTIMIZE_ERROR",
            status_code=500,
        )
    return ok(message, data)


@router.get(
    "/list",
    summary="List available poster files",
    description="List available poster files from the static posters directory.",
    responses={
        200: {
            "description": "Poster files listed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 25 poster files",
                        "data": {"files": ["default-movie.jpg", "default-tv.png"]},
                    }
                }
            },
        }
    },
)
def list_poster_files(logger: Any = Depends(get_logger)) -> JSONResponse:
    """
    List available poster files from the static posters directory.

    Returns just the filenames for dynamic discovery by the frontend.
    Used for default poster selection and asset management.

    Returns:
        List of available poster filenames
    """
    try:
        logger.debug("Serving GET /api/posters/list")

        # Same directory main.py mounts at /posters — resolved via STATIC_DIR,
        # which Docker points at /app/public (templates/ isn't in the image).
        posters_dir = get_static_dir() / "posters"
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        if not posters_dir.exists():
            return ok(
                "Posters directory not found",
                {"files": []},
            )

        files = [
            f.name
            for f in posters_dir.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_extensions
        ]

        return ok(
            f"Found {len(files)} poster files",
            {"files": sorted(files)},
        )

    except Exception as e:
        logger.error(f"Error listing poster files: {e}")
        return error(
            "Error listing poster files",
            code="POSTER_LIST_ERROR",
            status_code=500,
        )


# --- Additional named poster endpoints ---
