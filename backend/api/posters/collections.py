"""Poster collection create/add/remove/delete endpoints."""

import datetime
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

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
from backend.util.database import ChubDB


@router.post(
    "/collections",
    summary="Create poster collection",
    description="Create a new poster collection for grouping related posters.",
    responses={
        200: {
            "description": "Collection created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster collection created",
                        "data": {"collection": {"id": 1, "name": "My Posters"}},
                    }
                }
            },
        },
        400: {"description": "Field 'name' is required"},
        413: {"description": "Request body too large"},
        500: {"description": "Failed to create the collection"},
    },
)
async def create_poster_collection(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Create a new poster collection.

    Creates a named collection for grouping related poster
    assets together for bulk management operations.

    Returns:
        Created collection details
    """
    try:
        payload = await read_json_object(request)
        if payload is BODY_TOO_LARGE:
            return body_too_large_error()
        logger.debug(f"Serving POST /api/posters/collections with payload: {payload}")

        name = payload.get("name")
        if not name:
            return error(
                "Field 'name' is required", code="MISSING_NAME", status_code=400
            )

        description = payload.get("description", "")
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        row_id = db.poster.create_collection(name, description, created_at)
        created = db.poster.get_collection(row_id)

        return ok("Poster collection created", {"collection": created})

    except Exception as e:
        logger.error(f"Error creating poster collection: {e}")
        return error(
            "Error creating poster collection",
            code="POSTER_COLLECTION_CREATE_ERROR",
            status_code=500,
        )


@router.post(
    "/collections/{collection_id}/add",
    summary="Add poster to collection",
    description="Add a poster to an existing collection by collection ID.",
    responses={
        200: {
            "description": "Poster added to collection",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster added to collection",
                        "data": {"collection_id": 1, "poster_id": 42},
                    }
                }
            },
        },
        400: {"description": "Field 'poster_id' is required"},
        404: {"description": "Poster collection not found"},
        413: {"description": "Request body too large"},
        500: {"description": "Failed to add the poster to the collection"},
    },
)
async def add_to_collection(
    collection_id: int,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Add a poster to a collection.

    Associates a poster with the specified collection for
    grouped management and display.

    Args:
        collection_id: The collection to add the poster to

    Returns:
        Confirmation of the association
    """
    try:
        payload = await read_json_object(request)
        if payload is BODY_TOO_LARGE:
            return body_too_large_error()
        logger.debug(
            f"Serving POST /api/posters/collections/{collection_id}/add with payload: {payload}"
        )

        poster_id = payload.get("poster_id")
        if not poster_id:
            return error(
                "Field 'poster_id' is required",
                code="MISSING_POSTER_ID",
                status_code=400,
            )

        # Verify collection exists
        collection = db.poster.get_collection(collection_id)
        if not collection:
            return error(
                f"Poster collection {collection_id} not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        db.poster.add_collection_item(collection_id, poster_id)

        return ok(
            "Poster added to collection",
            {"collection_id": collection_id, "poster_id": poster_id},
        )

    except Exception as e:
        logger.error(f"Error adding poster to collection: {e}")
        return error(
            "Error adding poster to collection",
            code="POSTER_COLLECTION_ADD_ERROR",
            status_code=500,
        )


@router.delete(
    "/collections/{collection_id}/remove/{poster_id}",
    summary="Remove poster from collection",
    description="Remove a poster from a collection by collection and poster ID.",
    responses={
        200: {
            "description": "Poster removed from collection",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster removed from collection",
                        "data": {"collection_id": 1, "poster_id": 42},
                    }
                }
            },
        },
        404: {"description": "Poster not in this collection"},
        500: {"description": "Failed to remove the poster from the collection"},
    },
)
async def remove_from_collection(
    collection_id: int,
    poster_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Remove a poster from a collection.

    Removes the association between a poster and the specified
    collection without deleting either entity.

    Args:
        collection_id: The collection to remove the poster from
        poster_id: The poster to remove from the collection

    Returns:
        Confirmation of the removal
    """
    try:
        logger.debug(
            f"Serving DELETE /api/posters/collections/{collection_id}/remove/{poster_id}"
        )

        rows_deleted = db.poster.remove_collection_item(collection_id, poster_id)

        if rows_deleted == 0:
            return error(
                "Poster not found in collection",
                code="ITEM_NOT_FOUND",
                status_code=404,
            )

        return ok(
            "Poster removed from collection",
            {"collection_id": collection_id, "poster_id": poster_id},
        )

    except Exception as e:
        logger.error(f"Error removing poster from collection: {e}")
        return error(
            "Error removing poster from collection",
            code="POSTER_COLLECTION_REMOVE_ERROR",
            status_code=500,
        )


@router.delete(
    "/collections/{collection_id}",
    summary="Delete poster collection",
    description="Delete a poster collection and all of its membership rows. "
    "The underlying poster files are not touched.",
    responses={
        404: {"description": "Poster collection not found"},
        500: {"description": "Failed to delete the collection"},
    },
)
async def delete_poster_collection(
    collection_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Delete one collection and its membership rows, leaving the posters alone."""
    try:
        logger.debug(f"Serving DELETE /api/posters/collections/{collection_id}")

        existing = db.poster.get_collection(collection_id)
        if not existing:
            return error(
                f"Poster collection {collection_id} not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        db.poster.delete_collection(collection_id)

        return ok(
            "Poster collection deleted",
            {"collection_id": collection_id},
        )

    except Exception as e:
        logger.error(f"Error deleting poster collection: {e}")
        return error(
            "Error deleting poster collection",
            code="POSTER_COLLECTION_DELETE_ERROR",
            status_code=500,
        )
