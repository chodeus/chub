"""Catalog-wide poster reads: search, stats, collection list, source search."""

import os
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
from backend.util.config import ConfigError
from backend.util.database import ChubDB


@router.get(
    "/search",
    summary="Search poster cache",
    description="Search the poster cache by title with pagination and sorting.",
    responses={
        200: {
            "description": "Poster search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 42 posters",
                        "data": {
                            "total": 42,
                            "posters": [
                                {
                                    "id": 1,
                                    "title": "The Matrix",
                                    "year": 1999,
                                    "file": "The Matrix (1999).jpg",
                                }
                            ],
                        },
                    }
                }
            },
        }
    },
)
async def search_posters(
    query: Optional[str] = None,
    sort: Optional[str] = Query(
        None, description="Sort field (e.g. title, year, date_added)"
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Search the poster cache by title with pagination.

    Performs a text search against poster titles and returns
    paginated results with optional sorting.

    Args:
        query: Search string to match against poster titles
        sort: Sort field for ordering results
        limit: Maximum number of results to return
        offset: Number of results to skip for pagination

    Returns:
        Paginated list of matching posters with total count
    """
    try:
        logger.debug(f"Serving GET /api/posters/search query={query} sort={sort}")
        result = db.poster.search(query=query, limit=limit, offset=offset)
        return ok(f"Found {result['total']} posters", result)
    except Exception as e:
        logger.error(f"Error searching posters: {e}")
        return error(
            "Error searching posters",
            code="POSTER_SEARCH_ERROR",
            status_code=500,
        )


@router.get(
    "/stats",
    summary="Get unified poster statistics",
    description="Retrieve combined poster statistics from all sources with optional grouping.",
    responses={
        200: {
            "description": "Poster statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Poster statistics retrieved",
                        "data": {
                            "matched_stats": {
                                "total_matched": 150,
                                "uploaded": 120,
                            },
                            "poster_cache_count": 500,
                            "gdrive_stats": {},
                        },
                    }
                }
            },
        }
    },
)
async def get_poster_stats(
    groupBy: Optional[str] = Query(
        None, description="Group statistics by field (type, source)"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get combined poster statistics from all sources.

    Returns aggregated poster counts, match rates, orphan counts,
    and GDrive sync statistics. Supports grouping by type or source
    for more granular breakdowns.

    Args:
        groupBy: Optional grouping mode. 'type' groups by asset category,
                 'source' groups by folder path root.

    Returns:
        Unified poster statistics with optional grouping breakdown
    """
    try:
        logger.debug(f"Serving GET /api/posters/stats groupBy={groupBy}")
        matched = db.stats.get_matched_posters_stats()
        poster_count = db.stats.count_poster_cache()
        gdrive = db.stats.get_gdrive_stats()
        applied = db.stats.get_applied_breakdowns()

        data = {
            "matched_stats": matched,
            "poster_cache_count": poster_count,
            "gdrive_stats": gdrive,
            "applied_by_style": applied["by_style"],
            "applied_by_type": applied["by_type"],
            "applied_by_source": applied["by_source"],
        }

        if groupBy == "type":
            all_posters = db.poster.get_all_grouped()
            type_counts = {k: len(v) for k, v in all_posters.items()}
            data["by_type"] = type_counts
        elif groupBy == "source":
            all_posters = db.poster.search(query=None, limit=10000, offset=0)
            source_counts: dict[str, int] = {}
            for p in all_posters.get("posters", []):
                folder = p.get("folder", "") or ""
                root = folder.split(os.sep)[0] if folder else "unknown"
                source_counts[root] = source_counts.get(root, 0) + 1
            data["by_source"] = source_counts

        return ok("Poster statistics retrieved", data)
    except Exception as e:
        logger.error(f"Error retrieving poster stats: {e}")
        return error(
            "Error retrieving poster statistics",
            code="POSTER_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/collections",
    summary="Get poster collections",
    description="Retrieve all collections with poster associations.",
    responses={
        200: {
            "description": "Poster collections retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 5 collections",
                        "data": {
                            "collections": [
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
        },
        500: {"description": "Failed to read the poster collections"},
    },
)
async def get_poster_collections(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve all collections with poster associations.

    Returns the complete list of collections from the database
    including metadata and identifiers for poster management.

    Returns:
        List of all poster collections
    """
    try:
        logger.debug("Serving GET /api/posters/collections")
        collections = db.poster.get_collections()

        # Hydrate each collection with its poster contents + count. One join
        # per collection is fine — the table is small and rarely fetched.
        for col in collections:
            posters = db.poster.get_collection_posters(col["id"])
            col["posters"] = posters
            col["poster_count"] = len(posters)

        return ok(
            f"Retrieved {len(collections)} collections", {"collections": collections}
        )
    except Exception as e:
        logger.error(f"Error retrieving poster collections: {e}")
        return error(
            "Error retrieving collections",
            code="POSTER_COLLECTIONS_ERROR",
            status_code=500,
        )


@router.get(
    "/sources/gdrive/search",
    summary="Search GDrive poster sources",
    description="Search configured GDrive folder sources with file statistics.",
    responses={
        200: {
            "description": "GDrive sources retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 3 GDrive sources",
                        "data": {
                            "sources": [
                                {
                                    "id": "abc123",
                                    "name": "Movie Posters",
                                    "location": "/posters/movies",
                                    "file_count": 150,
                                    "size_bytes": 52428800,
                                    "last_updated": "2024-01-01T12:00:00Z",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
async def search_gdrive_sources(
    query: Optional[str] = None,
    folder: Optional[str] = Query(
        None, description="Filter by folder name or folder ID"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Search GDrive folder sources with file statistics.

    Returns configured GDrive folders filtered by search query
    and/or folder identifier, enriched with file count, size,
    and last-updated timestamps from cached statistics.

    Args:
        query: Search string to match against folder name or location
        folder: Filter by exact folder name or GDrive folder ID

    Returns:
        List of matching GDrive sources with statistics
    """
    try:
        logger.debug(
            f"Serving GET /api/posters/sources/gdrive/search query={query} folder={folder}"
        )
        from backend.util.config import load_config

        config = load_config()

        gdrive_list = []
        if hasattr(config, "sync_gdrive") and hasattr(
            config.sync_gdrive, "gdrive_list"
        ):
            for entry in config.sync_gdrive.gdrive_list:
                item = {"id": entry.id, "name": entry.name, "location": entry.location}

                # Apply folder filter
                if (
                    folder
                    and folder.lower() not in entry.name.lower()
                    and folder != entry.id
                ):
                    continue

                # Apply query filter
                if (
                    query
                    and query.lower() not in entry.name.lower()
                    and query.lower() not in entry.location.lower()
                ):
                    continue
                gdrive_list.append(item)

        stats = db.stats.get_gdrive_stats()
        stats_by_location = {s.get("location", ""): s for s in (stats or [])}

        for item in gdrive_list:
            loc_stats = stats_by_location.get(item["location"], {})
            item["file_count"] = loc_stats.get("file_count", 0)
            item["size_bytes"] = loc_stats.get("size_bytes", 0)
            item["last_updated"] = loc_stats.get("last_updated")

        return ok(f"Found {len(gdrive_list)} GDrive sources", {"sources": gdrive_list})
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error searching GDrive sources: {e}")
        return error(
            "Error searching GDrive sources",
            code="GDRIVE_SEARCH_ERROR",
            status_code=500,
        )
