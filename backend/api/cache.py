"""Read/delete endpoints for the media, collection and Plex caches, plus the
background refresh trigger."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.api.utils import (
    BODY_TOO_LARGE,
    body_too_large_error,
    build_cache_refresh_payload,
    error,
    get_database,
    get_logger,
    ok,
    read_request_json,
)
from backend.util.database import ChubDB

router = APIRouter(
    prefix="/api/cache",
    tags=["Media Cache"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Cache item not found"},
    },
)


def _page(rows: list, limit: Optional[int], offset: int) -> list:
    """Slice rows for the optional limit/offset query params.

    No params means the full result set, which existing callers rely on."""
    if limit is None and not offset:
        return rows
    end = offset + limit if limit is not None else None
    return rows[offset:end]


@router.get(
    "/media",
    summary="Get media cache",
    description="Retrieve all cached media items from the database.",
    responses={
        200: {
            "description": "Media cache retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 150 media cache items",
                        "data": {
                            "media_cache": [
                                {
                                    "id": 1,
                                    "title": "The Matrix",
                                    "year": 1999,
                                    "imdb_id": "tt0133093",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
def get_media_cache(
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Return media cache rows; without limit/offset the whole cache is returned."""
    try:
        logger.debug("Serving GET /api/cache/media")

        media_cache = db.media.get_all() or []
        page = _page(media_cache, limit, offset)

        return ok(
            f"Retrieved {len(page)} of {len(media_cache)} media cache items",
            {"media_cache": page, "total": len(media_cache)},
        )

    except Exception as e:
        logger.error(f"Error retrieving media cache: {e}")
        return error(
            "Error retrieving media cache",
            code="MEDIA_CACHE_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.get(
    "/collection",
    summary="Get collection cache",
    description="Retrieve all cached collection items from the database.",
    responses={
        200: {
            "description": "Collection cache retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 25 collection cache items",
                        "data": {
                            "collection_cache": [
                                {
                                    "id": 1,
                                    "title": "Marvel Cinematic Universe",
                                    "tmdb_id": "1399",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
def get_collection_cache(
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Return collection cache rows; without limit/offset the whole cache is returned."""
    try:
        logger.debug("Serving GET /api/cache/collection")

        collection_cache = db.collection.get_all() or []
        page = _page(collection_cache, limit, offset)

        return ok(
            f"Retrieved {len(page)} of {len(collection_cache)} collection cache items",
            {"collection_cache": page, "total": len(collection_cache)},
        )

    except Exception as e:
        logger.error(f"Error retrieving collection cache: {e}")
        return error(
            "Error retrieving collection cache",
            code="COLLECTION_CACHE_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.get(
    "/plex",
    summary="Get Plex cache",
    description="Retrieve all cached Plex media items from the database.",
    responses={
        200: {
            "description": "Plex cache retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 200 plex cache items",
                        "data": {
                            "plex_media_cache": [
                                {
                                    "id": 1,
                                    "title": "The Matrix",
                                    "plex_key": "12345",
                                    "library": "Movies",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
def get_plex_cache(
    limit: Optional[int] = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Return Plex cache rows; without limit/offset the whole cache is returned."""
    try:
        logger.debug("Serving GET /api/cache/plex")

        plex_cache = db.plex.get_all() or []
        page = _page(plex_cache, limit, offset)

        return ok(
            f"Retrieved {len(page)} of {len(plex_cache)} plex cache items",
            {"plex_media_cache": page, "total": len(plex_cache)},
        )

    except Exception as e:
        logger.error(f"Error retrieving plex cache: {e}")
        return error(
            "Error retrieving plex cache",
            code="PLEX_CACHE_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.post(
    "/refresh",
    summary="Refresh cache",
    description="Trigger background cache refresh for specified instances and libraries.",
    responses={
        200: {
            "description": "Cache refresh initiated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Cache refresh initiated",
                        "data": {"job_id": 123},
                    }
                }
            },
        },
        400: {"description": "Malformed JSON, or not an object of string lists"},
        413: {"description": "Request body too large"},
    },
)
async def refresh_cache(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Enqueue a cache_refresh job; empty instance lists mean auto-discover all."""
    try:
        payload = await read_request_json(request)
        if payload is BODY_TOO_LARGE:
            return body_too_large_error()

        logger.debug(f"Serving POST /api/cache/refresh with payload: {payload}")

        job_payload = build_cache_refresh_payload(payload)
        if job_payload is None:
            return error(
                "Invalid request body",
                code="INVALID_BODY",
                status_code=400,
            )

        # Use existing job system
        result = db.worker.enqueue_job("jobs", job_payload, job_type="cache_refresh")

        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(f"Cache refresh job queued: {job_id}")
            return ok(
                "Cache refresh initiated",
                {"job_id": job_id},
            )
        else:
            return error(
                f"Error enqueuing cache refresh: {result.get('message', 'Unknown error')}",
                code="CACHE_REFRESH_ENQUEUE_ERROR",
                status_code=500,
            )

    except Exception as e:
        logger.error(f"Error serving POST /api/cache/refresh: {e}")
        return error(
            "Error initiating cache refresh",
            code="CACHE_REFRESH_ERROR",
            status_code=500,
        )


@router.delete(
    "/media/{item_id}",
    summary="Delete media cache item",
    description="Delete a specific media cache item by ID.",
    responses={
        200: {
            "description": "Media cache item deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media cache item 123 deleted successfully",
                        "data": {"deleted_id": 123},
                    }
                }
            },
        },
        404: {"description": "Media cache item not found"},
    },
)
def delete_media_cache_item(
    item_id: int, logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> JSONResponse:
    """Delete one media cache row; 404 when the id is unknown. Not undoable."""
    try:
        logger.debug(f"Serving DELETE /api/cache/media/{item_id}")

        if not db.media.get_by_id(item_id):
            return error(
                f"Media cache item {item_id} not found",
                code="MEDIA_CACHE_NOT_FOUND",
                status_code=404,
            )

        db.media.delete_by_id(item_id)

        logger.info(f"Deleted media cache item id={item_id}")
        return ok(
            f"Media cache item {item_id} deleted successfully",
            {"deleted_id": item_id},
        )

    except Exception as e:
        logger.error(f"Error deleting media cache item {item_id}: {e}")
        return error(
            "Error deleting media cache item",
            code="MEDIA_CACHE_DELETE_ERROR",
            status_code=500,
        )


@router.delete(
    "/collection/{item_id}",
    summary="Delete collection cache item",
    description="Delete a specific collection cache item by ID.",
    responses={
        200: {
            "description": "Collection cache item deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Collection cache item 123 deleted successfully",
                        "data": {"deleted_id": 123},
                    }
                }
            },
        },
        404: {"description": "Collection cache item not found"},
    },
)
def delete_collection_cache_item(
    item_id: int, logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> JSONResponse:
    """Delete one collection cache row; 404 when the id is unknown. Not undoable."""
    try:
        logger.debug(f"Serving DELETE /api/cache/collection/{item_id}")

        if not db.collection.get_by_id(item_id):
            return error(
                f"Collection cache item {item_id} not found",
                code="COLLECTION_CACHE_NOT_FOUND",
                status_code=404,
            )

        db.collection.delete_by_id(item_id)

        logger.info(f"Deleted collection cache item id={item_id}")
        return ok(
            f"Collection cache item {item_id} deleted successfully",
            {"deleted_id": item_id},
        )

    except Exception as e:
        logger.error(f"Error deleting collection cache item {item_id}: {e}")
        return error(
            "Error deleting collection cache item",
            code="COLLECTION_CACHE_DELETE_ERROR",
            status_code=500,
        )
