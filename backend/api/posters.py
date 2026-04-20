"""
Poster management API endpoints for CHUB.

Provides poster operations including statistics, file management,
upload operations, and directory analysis functionality.
"""

import datetime
import os
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.api.utils import error, get_database, get_logger, ok
from backend.modules.sync_gdrive import SyncGDrive
from backend.modules.unmatched_assets import UnmatchedAssets
from backend.util.database import ChubDB

router = APIRouter(
    prefix="/api/posters",
    tags=["Posters"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Poster or resource not found"},
    },
)


# --- New endpoints: search, stats, browse, collections, duplicates ---


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
            f"Error searching posters: {str(e)}",
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
                            "orphaned_count": 12,
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
        orphaned_count = db.stats.count_orphaned_posters()
        gdrive = db.stats.get_gdrive_stats()

        data = {
            "matched_stats": matched,
            "poster_cache_count": poster_count,
            "orphaned_count": orphaned_count,
            "gdrive_stats": gdrive,
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
            f"Error retrieving poster statistics: {str(e)}",
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
        }
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
        collections = db.poster.execute_query(
            "SELECT * FROM poster_collections ORDER BY name", fetch_all=True
        ) or []
        return ok(
            f"Retrieved {len(collections)} collections", {"collections": collections}
        )
    except Exception as e:
        logger.error(f"Error retrieving poster collections: {e}")
        return error(
            f"Error retrieving collections: {str(e)}",
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
    except Exception as e:
        logger.error(f"Error searching GDrive sources: {e}")
        return error(
            f"Error searching GDrive sources: {str(e)}",
            code="GDRIVE_SEARCH_ERROR",
            status_code=500,
        )


@router.get(
    "/sources/assets/search",
    summary="Search local asset sources",
    description="Search local poster assets in the poster cache with pagination.",
    responses={
        200: {
            "description": "Asset search results retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 25 asset posters",
                        "data": {
                            "total": 25,
                            "posters": [
                                {
                                    "id": 1,
                                    "title": "The Matrix",
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
async def search_asset_sources(
    query: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Search local poster assets in the poster cache.

    Performs a text search against locally cached poster assets
    with pagination support for browsing large collections.

    Args:
        query: Search string to match against asset titles
        limit: Maximum number of results to return
        offset: Number of results to skip for pagination

    Returns:
        Paginated list of matching asset posters with total count
    """
    try:
        logger.debug(f"Serving GET /api/posters/sources/assets/search query={query}")
        result = db.poster.search(query=query, limit=limit, offset=offset)
        return ok(f"Found {result['total']} asset posters", result)
    except Exception as e:
        logger.error(f"Error searching asset sources: {e}")
        return error(
            f"Error searching assets: {str(e)}",
            code="ASSET_SEARCH_ERROR",
            status_code=500,
        )


@router.get(
    "/duplicates",
    summary="Find duplicate posters",
    description="Find poster entries with duplicate title, year, and season combinations.",
    responses={
        200: {
            "description": "Duplicate poster groups retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 3 duplicate groups",
                        "data": {
                            "duplicates": [
                                {
                                    "key": "The Matrix-1999",
                                    "count": 2,
                                    "posters": [],
                                }
                            ],
                            "total": 3,
                        },
                    }
                }
            },
        }
    },
)
async def get_poster_duplicates(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Find poster entries with the same title, year, and season.

    Scans the poster cache for duplicate entries that share
    identical metadata, useful for cleanup and deduplication.

    Returns:
        List of duplicate groups with poster details and total count
    """
    try:
        logger.debug("Serving GET /api/posters/duplicates")
        duplicates = db.poster.find_duplicates()
        return ok(
            f"Found {len(duplicates)} duplicate groups",
            {"duplicates": duplicates, "total": len(duplicates)},
        )
    except Exception as e:
        logger.error(f"Error finding poster duplicates: {e}")
        return error(
            f"Error finding duplicates: {str(e)}",
            code="POSTER_DUPLICATES_ERROR",
            status_code=500,
        )


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
async def auto_match_posters(
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
            f"Error initiating auto-match: {str(e)}",
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
async def browse_posters(
    owner: Optional[str] = Query(None, description="Filter by GDrive owner name"),
    type: Optional[str] = Query(None, description="Filter by asset type: movie, season"),
    query: Optional[str] = Query(None, description="Search by title"),
    limit: int = Query(60, ge=0, le=200, description="Results per page (0 for owners only)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Browse cached poster files with optional filtering and pagination.

    Args:
        owner: Filter by GDrive owner (derived from folder path)
        type: Filter by asset type (movie or season)
        query: Search by title
        limit: Results per page
        offset: Pagination offset

    Returns:
        Paginated poster list with available owner names for filtering
    """
    try:
        logger.debug("Serving GET /api/posters/browse")
        result = db.poster.browse(
            owner=owner, asset_type=type, query=query, limit=limit, offset=offset
        )
        owners = db.poster.get_distinct_owners()
        result["owners"] = owners
        return ok(
            f"Retrieved {len(result['items'])} of {result['total']} posters", result
        )
    except Exception as e:
        logger.error(f"Error browsing posters: {e}")
        return error(
            f"Error browsing posters: {str(e)}",
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

        # Write file
        contents = await file.read()
        with open(dest_path, "wb") as f:
            f.write(contents)

        logger.info(f"Poster uploaded: {dest_path}")
        return ok(
            "Poster uploaded successfully",
            {"filename": safe_name, "path": dest_path, "size_bytes": len(contents)},
        )

    except Exception as e:
        logger.error(f"Error uploading poster: {e}")
        return error(
            f"Error uploading poster: {str(e)}",
            code="POSTER_UPLOAD_ERROR",
            status_code=500,
        )


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
        }
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
        payload = await request.json()
        logger.debug(f"Serving POST /api/posters/collections with payload: {payload}")

        name = payload.get("name")
        if not name:
            return error("Field 'name' is required", code="MISSING_NAME", status_code=400)

        description = payload.get("description", "")
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        row_id = db.poster.execute_query(
            "INSERT INTO poster_collections (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, created_at),
            last_row_id=True,
        )

        created = db.poster.execute_query(
            "SELECT * FROM poster_collections WHERE id=?",
            (row_id,),
            fetch_one=True,
        )

        return ok("Poster collection created", {"collection": created})

    except Exception as e:
        logger.error(f"Error creating poster collection: {e}")
        return error(
            f"Error creating poster collection: {str(e)}",
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
        }
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
        payload = await request.json()
        logger.debug(f"Serving POST /api/posters/collections/{collection_id}/add with payload: {payload}")

        poster_id = payload.get("poster_id")
        if not poster_id:
            return error("Field 'poster_id' is required", code="MISSING_POSTER_ID", status_code=400)

        # Verify collection exists
        collection = db.poster.execute_query(
            "SELECT * FROM poster_collections WHERE id=?",
            (collection_id,),
            fetch_one=True,
        )
        if not collection:
            return error(
                f"Poster collection {collection_id} not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        db.poster.execute_query(
            "INSERT OR IGNORE INTO poster_collection_items (collection_id, poster_id) VALUES (?, ?)",
            (collection_id, poster_id),
        )

        return ok(
            "Poster added to collection",
            {"collection_id": collection_id, "poster_id": poster_id},
        )

    except Exception as e:
        logger.error(f"Error adding poster to collection: {e}")
        return error(
            f"Error adding poster to collection: {str(e)}",
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
        }
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
        logger.debug(f"Serving DELETE /api/posters/collections/{collection_id}/remove/{poster_id}")

        rows_deleted = db.poster.execute_query(
            "DELETE FROM poster_collection_items WHERE collection_id=? AND poster_id=?",
            (collection_id, poster_id),
        )

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
            f"Error removing poster from collection: {str(e)}",
            code="POSTER_COLLECTION_REMOVE_ERROR",
            status_code=500,
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
        }
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
    from PIL import Image

    try:
        body = await request.json()
    except Exception:
        body = {}

    max_width = body.get("max_width", 1000)
    max_height = body.get("max_height", 1500)
    target_format = body.get("format", "jpeg").lower()
    quality = max(1, min(100, body.get("quality", 85)))
    mode = body.get("mode", "report")

    format_map = {"jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP", "png": "PNG"}
    pil_format = format_map.get(target_format, "JPEG")
    ext_map = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}
    target_ext = ext_map.get(pil_format, ".jpg")

    try:
        # Get all posters from cache
        posters = db.poster.get_all()
        if not posters:
            return ok("No posters found to optimize", {
                "processed": 0, "skipped": 0, "failed": 0,
                "bytes_saved": 0, "mode": mode,
            })

        processed = 0
        skipped = 0
        failed = 0
        bytes_saved = 0
        details = []

        for poster in posters:
            file_path = poster.get("file", "")
            folder = poster.get("folder", "")
            full_path = os.path.join(folder, file_path) if folder else file_path

            if not full_path or not os.path.isfile(full_path):
                skipped += 1
                continue

            try:
                original_size = os.path.getsize(full_path)

                with Image.open(full_path) as img:
                    w, h = img.size
                    needs_resize = w > max_width or h > max_height
                    needs_convert = not full_path.lower().endswith(target_ext)

                    if not needs_resize and not needs_convert:
                        skipped += 1
                        continue

                    if mode == "report":
                        details.append({
                            "file": full_path,
                            "size": original_size,
                            "dimensions": f"{w}x{h}",
                            "needs_resize": needs_resize,
                            "needs_convert": needs_convert,
                        })
                        processed += 1
                        continue

                    # Actually optimize
                    if needs_resize:
                        img.thumbnail((max_width, max_height), Image.LANCZOS)

                    img = img.convert("RGB") if pil_format in ("JPEG",) else img

                    # Save to temp file, then replace
                    import tempfile
                    with tempfile.NamedTemporaryFile(
                        suffix=target_ext, delete=False, dir=os.path.dirname(full_path)
                    ) as tmp:
                        save_kwargs = {"format": pil_format}
                        if pil_format in ("JPEG", "WEBP"):
                            save_kwargs["quality"] = quality
                            save_kwargs["optimize"] = True
                        img.save(tmp.name, **save_kwargs)
                        new_size = os.path.getsize(tmp.name)

                        if new_size < original_size:
                            import shutil
                            shutil.move(tmp.name, full_path)
                            bytes_saved += original_size - new_size
                            processed += 1
                        else:
                            os.unlink(tmp.name)
                            skipped += 1

            except Exception as e:
                logger.warning(f"Failed to optimize {full_path}: {e}")
                failed += 1

        saved_mb = round(bytes_saved / (1024 * 1024), 1)
        result_data = {
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "bytes_saved": bytes_saved,
            "mode": mode,
        }
        if mode == "report" and details:
            result_data["candidates"] = details[:100]

        msg = (
            f"Found {processed} posters to optimize"
            if mode == "report"
            else f"Optimized {processed} posters, saved {saved_mb} MB"
        )
        return ok(msg, result_data)

    except Exception as e:
        logger.error(f"Error optimizing posters: {e}", exc_info=True)
        return error(
            f"Error optimizing posters: {str(e)}",
            code="OPTIMIZE_ERROR",
            status_code=500,
        )


@router.post(
    "/duplicates/{group_id}/resolve",
    summary="Resolve poster duplicates",
    description="Resolve a group of duplicate posters by selecting the preferred version.",
    responses={
        200: {
            "description": "Duplicate resolution result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Duplicate resolution not yet implemented",
                        "data": {"status": "not_implemented"},
                    }
                }
            },
        }
    },
)
async def resolve_poster_duplicates(
    group_id: str,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Resolve a group of duplicate posters.

    Keeps the specified poster and removes the others from the cache.
    The group_id is a comma-separated list of poster IDs from the
    duplicates endpoint. The request body should contain keepId.

    Args:
        group_id: Comma-separated poster IDs in the duplicate group
        request: Request containing keepId and optional removeIds

    Returns:
        Resolution result with kept and removed poster details
    """
    try:
        logger.debug(f"Serving POST /api/posters/duplicates/{group_id}/resolve")

        payload = await request.json()
        keep_id = payload.get("keepId")
        remove_ids = payload.get("removeIds", [])

        if not keep_id:
            return error(
                "keepId is required",
                code="MISSING_KEEP_ID",
                status_code=400,
            )

        # If removeIds not specified, parse from group_id
        if not remove_ids:
            try:
                all_ids = [int(i.strip()) for i in group_id.split(",")]
                remove_ids = [i for i in all_ids if i != int(keep_id)]
            except ValueError:
                return error(
                    "Invalid group_id format",
                    code="INVALID_GROUP_ID",
                    status_code=400,
                )

        removed = []
        for rid in remove_ids:
            record = db.poster.delete_by_integer_id(int(rid))
            if record:
                removed.append(rid)

        logger.info(f"Resolved duplicates: kept {keep_id}, removed {removed}")
        return ok(
            f"Resolved {len(removed)} duplicate posters",
            {"kept_id": keep_id, "removed_ids": removed, "removed_count": len(removed)},
        )

    except Exception as e:
        logger.error(f"Error resolving poster duplicates: {e}")
        return error(
            f"Error resolving duplicates: {str(e)}",
            code="DUPLICATE_RESOLVE_ERROR",
            status_code=500,
        )


@router.post(
    "/sync-metadata",
    summary="Bulk sync poster metadata",
    description="Enqueue a full poster_renamerr job to sync metadata for all posters.",
    responses={
        200: {
            "description": "Bulk metadata sync job enqueued",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Bulk metadata sync initiated",
                        "data": {"job_id": 123},
                    }
                }
            },
        }
    },
)
async def bulk_sync_metadata(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Trigger bulk metadata synchronization for all posters.

    Enqueues a full poster_renamerr job to refresh metadata
    for every poster in the cache.

    Returns:
        Job ID for tracking the bulk sync operation
    """
    try:
        logger.debug("Serving POST /api/posters/sync-metadata")
        result = db.worker.enqueue_job(
            "jobs",
            {"module_name": "poster_renamerr"},
            job_type="module_run",
        )
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok("Bulk metadata sync initiated", {"job_id": job_id})
        return error(
            "Error enqueuing bulk metadata sync",
            code="BULK_SYNC_ERROR",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error initiating bulk metadata sync: {e}")
        return error(
            f"Error initiating bulk metadata sync: {str(e)}",
            code="BULK_SYNC_ERROR",
            status_code=500,
        )


@router.get(
    "/list",
    summary="List available poster files",
    description="List available poster files from the templates/posters directory.",
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
async def list_poster_files(logger: Any = Depends(get_logger)) -> JSONResponse:
    """
    List available poster files from templates/posters directory.

    Returns just the filenames for dynamic discovery by the frontend.
    Used for default poster selection and asset management.

    Returns:
        List of available poster filenames
    """
    try:
        logger.debug("Serving GET /api/posters/list")

        posters_dir = Path(__file__).parents[2] / "templates" / "posters"
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
            f"Error listing poster files: {str(e)}",
            code="POSTER_LIST_ERROR",
            status_code=500,
        )


# --- Additional named poster endpoints ---


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
            f"Error retrieving matched posters statistics: {str(e)}",
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
            f"Error retrieving unmatched assets statistics: {str(e)}",
            code="UNMATCHED_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/unmatched/details",
    summary="Get detailed unmatched assets list",
    description="Retrieve per-item unmatched assets with external IDs for poster lookup.",
)
async def get_unmatched_assets_details(logger: Any = Depends(get_logger)) -> JSONResponse:
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
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving unmatched details: {e}")
        return error(
            f"Error retrieving unmatched assets details: {str(e)}",
            code="UNMATCHED_DETAILS_ERROR",
            status_code=500,
        )


@router.get(
    "/gdrive/stats",
    summary="Get GDrive synchronization statistics",
    description="Retrieve and refresh GDrive sync statistics and poster data.",
    responses={
        200: {
            "description": "GDrive statistics retrieved and refreshed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "GDrive statistics retrieved and refreshed",
                        "data": {
                            "gdrive_stats": {
                                "total_folders": 5,
                                "synced_posters": 500,
                                "pending_sync": 25,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def get_gdrive_stats(
    logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> JSONResponse:
    """
    Retrieve GDrive synchronization statistics.

    Refreshes poster statistics from GDrive and returns current
    sync status, folder counts, and transfer metrics for monitoring
    GDrive integration health.

    Returns:
        Current GDrive sync statistics and folder information
    """
    try:
        logger.debug("Serving GET /api/posters/gdrive/stats")
        gdrive_logger = logger.get_adapter("GDriveStats")

        syncer = SyncGDrive(logger=gdrive_logger)
        syncer.refresh_all_poster_stats()

        stats = db.stats.get_gdrive_stats()

        return ok(
            "GDrive statistics retrieved and refreshed",
            {"gdrive_stats": stats},
        )

    except Exception as e:
        logger.error(f"Error retrieving GDrive stats: {e}")
        return error(
            f"Error retrieving GDrive statistics: {str(e)}",
            code="GDRIVE_STATS_ERROR",
            status_code=500,
        )


@router.post(
    "/gdrive/sync",
    summary="Sync GDrive folders",
    description="Enqueue GDrive synchronization jobs for selected folders.",
    responses={
        200: {
            "description": "GDrive sync jobs created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "GDrive sync started for 2 folders: Movies, TV Shows",
                        "data": {
                            "jobs": [
                                {"name": "Movies", "job_id": 123},
                                {"name": "TV Shows", "job_id": 124},
                            ]
                        },
                    }
                }
            },
        },
        400: {"description": "No GDrive folder names provided"},
    },
)
async def sync_gdrive_folders(
    gdrive_names: List[str] = Query(
        ..., description="Names of the GDrive folders to sync"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Enqueue GDrive synchronization jobs for selected folders.

    Creates background sync jobs for each specified GDrive folder
    to download and organize poster assets. Jobs can be monitored
    through the job management endpoints.

    Args:
        gdrive_names: List of GDrive folder names to synchronize

    Returns:
        Job IDs and status for tracking sync operations
    """
    try:
        gdrive_logger = logger.get_adapter("GDriveFolder")
        gdrive_logger.debug(
            f"Serving POST /api/posters/gdrive/sync with names: {gdrive_names}"
        )

        if not gdrive_names:
            return error(
                "At least one GDrive folder name is required",
                code="GDRIVE_NAMES_REQUIRED",
                status_code=400,
            )

        started = []
        job_ids = []

        for name in gdrive_names:
            job_result = db.worker.enqueue_job(
                "jobs", payload={"gdrive_name": name}, job_type="sync_gdrive"
            )
            job_id = job_result.get("data", {}).get("job_id")
            started.append(name)
            job_ids.append({"name": name, "job_id": job_id})

        if len(job_ids) == 1:
            return ok(
                f"GDrive sync started for '{started[0]}'",
                {"job_id": job_ids[0]["job_id"], "name": job_ids[0]["name"]},
            )

        return ok(
            f"GDrive sync started for {len(started)} folders: {', '.join(started)}",
            {"jobs": job_ids},
        )

    except Exception as e:
        logger.error(f"Error starting GDrive sync: {e}")
        return error(
            f"Error starting GDrive synchronization: {str(e)}",
            code="GDRIVE_SYNC_START_ERROR",
            status_code=500,
        )


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
async def analyze_poster_directory(
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
        except Exception:  # noqa: S110 — config may not be loaded at boot
            config = None

        if not location:
            # Default to poster destination from config
            if config is not None:
                location = getattr(config.poster_renamerr, "destination", None)
            if not location:
                return error(
                    "Location parameter is required and no default destination configured",
                    code="LOCATION_REQUIRED",
                    status_code=400,
                )

        # Restrict to configured allowed roots
        if config is not None and not is_path_allowed(location, config):
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

    except Exception as e:
        logger.error(f"Error analyzing poster location: {e}")
        return error(
            f"Error analyzing poster location: {str(e)}",
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
async def preview_poster_file(
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

        # Restrict `location` to configured allowed roots — otherwise an
        # authenticated caller could point at arbitrary dirs (/etc, /root).
        from backend.util.config import load_config
        from backend.util.path_safety import is_path_allowed

        try:
            config = load_config()
        except Exception:  # noqa: S110 — fail closed below
            config = None

        if config is None or not is_path_allowed(location, config):
            return error(
                "Access denied - path outside allowed directory",
                code="PATH_TRAVERSAL_DENIED",
                status_code=403,
            )

        base_dir = Path(location).resolve()
        file_path = (base_dir / path).resolve()

        # Path-containment check (is_relative_to avoids the `str.startswith`
        # bypass where `/posters_evil/x` slipped past a `/posters` prefix).
        try:
            file_path.relative_to(base_dir)
        except ValueError:
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

    except Exception as e:
        logger.error(f"Error serving poster preview: {e}")
        return error(
            f"Error serving poster preview: {str(e)}",
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
async def upload_media_posters(
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
            return error(
                f"Upload failed for media cache item {media_id}: {result.get('message', 'Unknown error')}",
                code="MEDIA_UPLOAD_FAILED",
                status_code=500,
            )

    except Exception as e:
        logger.error(f"Error uploading media cache item {media_id}: {e}")
        return error(
            f"Error triggering upload: {str(e)}",
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
async def upload_collection_posters(
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
            return error(
                f"Upload failed for collection cache item {collection_id}: {result.get('message', 'Unknown error')}",
                code="COLLECTION_UPLOAD_FAILED",
                status_code=500,
            )

    except Exception as e:
        logger.error(f"Error uploading collection cache item {collection_id}: {e}")
        return error(
            f"Error triggering upload: {str(e)}",
            code="COLLECTION_UPLOAD_ERROR",
            status_code=500,
        )


# --- Named-path poster endpoints (must precede /{poster_id} catch-all) ---


@router.post(
    "/backfill-dimensions",
    summary="Backfill poster width/height",
    description="Walk poster_cache rows missing width/height and populate "
    "them by opening the file with PIL. Processes up to `limit` rows per call "
    "so it can be run incrementally without blocking the event loop.",
)
async def backfill_poster_dimensions(
    limit: int = 200,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        limit = max(1, min(limit, 2000))
        rows = db.worker.execute_query(
            "SELECT id, file FROM poster_cache WHERE width IS NULL OR height IS NULL "
            "LIMIT ?",
            (limit,),
            fetch_all=True,
        ) or []

        from PIL import Image

        updated = 0
        skipped = 0
        for r in rows:
            path = r["file"]
            if not path or not os.path.isfile(path):
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
    except Exception as e:
        logger.error(f"Error backfilling poster dimensions: {e}")
        return error(
            f"Error backfilling poster dimensions: {str(e)}",
            code="BACKFILL_DIMENSIONS_ERROR",
            status_code=500,
        )


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
            f"Error listing low-resolution posters: {str(e)}",
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
            f"Error listing posters added_since: {str(e)}",
            code="ADDED_SINCE_ERROR",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Plex Metadata / Poster Cleanarr endpoints
# ---------------------------------------------------------------------------


def _get_plex_path(request: Request) -> Optional[str]:
    """
    Resolve the Plex filesystem path from config. The poster_cleanarr module
    config is the canonical place — general config doesn't store this.
    """
    try:
        from backend.util.config import load_config

        cfg = load_config()
    except Exception:
        return None
    section = getattr(cfg, "poster_cleanarr", None)
    if section is not None:
        pp = getattr(section, "plex_path", None)
        if pp:
            return str(pp)
    return None


@router.get("/plex-metadata/by-media")
async def list_plex_metadata_by_media(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    only_bloat: bool = Query(False),
    force: bool = Query(False, description="Bypass the 5-min scan cache"),
    logger: Any = Depends(get_logger),
):
    """
    Group Plex Metadata poster variants by their owning media item.

    Returns `{bundles: [...], total, limit, offset, stats}`. When `only_bloat`
    is true, bundles with zero bloat variants are filtered out.
    """
    try:
        from backend.util.plex_metadata import scan_bundles

        plex_path = _get_plex_path(request)
        if not plex_path:
            return error(
                "Plex path is not configured",
                code="PLEX_PATH_UNSET",
                status_code=400,
            )
        scan = scan_bundles(plex_path, force=force)
        bundles = scan["bundles"]
        if only_bloat:
            bundles = [b for b in bundles if any(not v["active"] for v in b["variants"])]
        total = len(bundles)
        page = bundles[offset : offset + limit]
        return ok(
            f"Retrieved {len(page)} of {total} bundles",
            {
                "bundles": page,
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": scan["stats"],
            },
        )
    except Exception as e:
        logger.error(f"Error listing plex metadata bundles: {e}")
        return error(
            f"Error listing plex metadata: {str(e)}",
            code="PLEX_METADATA_LIST_ERROR",
            status_code=500,
        )


@router.get("/plex-metadata/bloat")
async def list_plex_metadata_bloat(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    force: bool = Query(False),
    logger: Any = Depends(get_logger),
):
    """Flat list of bloat variants across all bundles, largest first."""
    try:
        from backend.util.plex_metadata import get_bloat_flat, scan_bundles

        plex_path = _get_plex_path(request)
        if not plex_path:
            return error("Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400)
        items = get_bloat_flat(plex_path, force=force)
        total = len(items)
        page = items[offset : offset + limit]
        stats = scan_bundles(plex_path, force=False)["stats"]
        return ok(
            f"Retrieved {len(page)} of {total} bloat files",
            {
                "items": page,
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": stats,
            },
        )
    except Exception as e:
        logger.error(f"Error listing plex metadata bloat: {e}")
        return error(
            f"Error listing plex metadata bloat: {str(e)}",
            code="PLEX_METADATA_BLOAT_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/cleanup")
async def run_plex_metadata_cleanup(
    request: Request,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
):
    """
    Enqueue a `poster_cleanarr` job. Request body:
        {
          "mode": "report" | "move" | "remove",
          "empty_trash": bool,
          "clean_bundles": bool,
          "optimize_db": bool,
          "target_paths": [str, ...]   # optional; if present, only these files are processed
        }
    """
    try:
        body: dict = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        mode = (body.get("mode") or "report").lower()
        if mode not in ("report", "move", "remove"):
            return error(
                f"Invalid mode '{mode}'", code="INVALID_MODE", status_code=400
            )
        payload = {
            "module_name": "poster_cleanarr",
            "overrides": {
                "mode": mode,
                "empty_trash": bool(body.get("empty_trash")),
                "clean_bundles": bool(body.get("clean_bundles")),
                "optimize_db": bool(body.get("optimize_db")),
            },
        }
        target_paths = body.get("target_paths")
        if isinstance(target_paths, list) and target_paths:
            payload["overrides"]["target_paths"] = [str(p) for p in target_paths]

        result = db.worker.enqueue_job("jobs", payload, job_type="module_run")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(f"Poster cleanarr cleanup enqueued (mode={mode}, job_id={job_id})")
            return ok("Cleanup job enqueued", {"job_id": job_id, "mode": mode})
        return error("Failed to enqueue cleanup", code="ENQUEUE_FAILED", status_code=500)
    except Exception as e:
        logger.error(f"Error enqueuing cleanup: {e}")
        return error(
            f"Error enqueuing cleanup: {str(e)}",
            code="CLEANUP_ENQUEUE_ERROR",
            status_code=500,
        )


@router.delete("/plex-metadata/variant")
async def delete_plex_metadata_variant(
    request: Request,
    logger: Any = Depends(get_logger),
):
    """Delete a single variant file. Body: `{path: str}`."""
    try:
        from backend.util.plex_metadata import delete_variant

        body = await request.json()
        path = (body or {}).get("path")
        if not isinstance(path, str) or not path:
            return error("Missing 'path'", code="MISSING_PATH", status_code=400)
        plex_path = _get_plex_path(request)
        if not plex_path:
            return error("Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400)
        ok_ = delete_variant(path, plex_path=plex_path)
        if not ok_:
            return error(
                "Failed to delete variant (path outside Plex metadata or I/O error)",
                code="VARIANT_DELETE_FAILED",
                status_code=400,
            )
        return ok("Variant deleted", {"path": path})
    except Exception as e:
        logger.error(f"Error deleting variant: {e}")
        return error(
            f"Error deleting variant: {str(e)}",
            code="VARIANT_DELETE_ERROR",
            status_code=500,
        )


@router.post("/plex-metadata/set-active")
async def set_plex_metadata_active(
    request: Request,
    logger: Any = Depends(get_logger),
):
    """
    Make a specific variant the active poster in Plex. Body:
        { "rating_key": int, "path": str }

    Uses plexapi's `item.uploadPoster(filepath=...)` — Plex re-ingests the
    file and points the item's `user_thumb_url` at the new hash. The old
    variant stays on disk and becomes bloat (cleanable from the same UI).
    """
    try:
        from backend.util.plex_metadata import invalidate_cache

        body = await request.json()
        rating_key = (body or {}).get("rating_key")
        path = (body or {}).get("path")
        if not rating_key or not isinstance(path, str) or not path:
            return error(
                "Missing rating_key or path",
                code="MISSING_PARAMS",
                status_code=400,
            )

        # Path-injection guard: only allow files inside Plex's Metadata dir.
        # Without this, a caller could upload ANY file on the server as a
        # Plex poster by passing an arbitrary filesystem path.
        plex_path = _get_plex_path(request)
        if not plex_path:
            return error("Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400)
        metadata_dir = os.path.realpath(os.path.join(plex_path, "Metadata"))
        safe_path = os.path.realpath(path)
        if not safe_path.startswith(metadata_dir + os.sep):
            return error("Path outside Plex metadata dir", code="INVALID_PATH", status_code=400)
        if not os.path.isfile(safe_path):
            return error("Variant file not found on disk", code="FILE_NOT_FOUND", status_code=404)

        from backend.util.config import load_config

        cfg = load_config()
        # Pick the first configured Plex instance — CHUB typically has one.
        plex_instances = (
            getattr(getattr(cfg, "instances", None), "plex", None) or {}
        )
        instance_cfg = next(iter(plex_instances.values()), None) if plex_instances else None
        if instance_cfg is None:
            return error(
                "No Plex instance configured",
                code="NO_PLEX_INSTANCE",
                status_code=400,
            )

        from plexapi.server import PlexServer

        server = PlexServer(instance_cfg.url, instance_cfg.api)
        item = server.fetchItem(int(rating_key))
        if item is None:
            return error("Plex item not found", code="ITEM_NOT_FOUND", status_code=404)
        item.uploadPoster(filepath=safe_path)
        invalidate_cache()
        return ok("Active poster updated", {"rating_key": rating_key, "path": safe_path})
    except Exception as e:
        logger.error(f"Error setting active poster: {e}")
        return error(
            f"Error setting active poster: {str(e)}",
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
    plex_path = _get_plex_path(request)
    if not plex_path:
        return error("Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400)
    metadata_dir = os.path.realpath(os.path.join(plex_path, "Metadata"))
    real = os.path.realpath(path)
    if not real.startswith(metadata_dir + os.sep) or not os.path.isfile(real):
        return error("Invalid path", code="INVALID_PATH", status_code=400)
    return FileResponse(real, media_type="image/jpeg")



# --- Parameterized poster ID endpoints ---


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
async def get_poster(
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
            f"Error retrieving poster: {str(e)}",
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
        404: {"description": "Poster or file not found"},
    },
)
async def get_poster_thumbnail(
    poster_id: int,
    width: int = Query(200, ge=50, le=500, description="Thumbnail width in pixels"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Any:
    """
    Get a cached thumbnail of a poster image.

    Generates a downsized JPEG thumbnail on first request and caches it
    in a .thumbnails subdirectory. Subsequent requests serve from cache.

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

        # Resolve to a real path to prevent path traversal
        full_path = os.path.realpath(raw_path)
        if not os.path.isfile(full_path):
            return error(
                "Poster file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        # Build thumbnail cache path using resolved directory
        safe_dir = os.path.dirname(full_path)
        thumb_dir = os.path.join(safe_dir, ".thumbnails")
        thumb_name = f"{poster_id}_w{width}.jpg"
        thumb_path = os.path.join(thumb_dir, thumb_name)

        # Serve from cache if fresh
        if os.path.isfile(thumb_path):
            src_mtime = os.path.getmtime(full_path)
            thumb_mtime = os.path.getmtime(thumb_path)
            if thumb_mtime >= src_mtime:
                return FileResponse(thumb_path, media_type="image/jpeg")

        # Generate thumbnail
        from PIL import Image

        os.makedirs(thumb_dir, exist_ok=True)
        with Image.open(full_path) as img:
            aspect = img.height / img.width
            target_height = int(width * aspect)
            img.thumbnail((width, target_height), Image.LANCZOS)
            img.convert("RGB").save(thumb_path, "JPEG", quality=60, optimize=True)

        return FileResponse(thumb_path, media_type="image/jpeg")

    except Exception as e:
        logger.error(f"Error generating thumbnail for poster {poster_id}: {e}")
        return error(
            f"Error generating thumbnail: {str(e)}",
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
        404: {"description": "Poster or file not found"},
    },
)
async def download_poster(
    poster_id: int,
    size: Optional[int] = Query(None, ge=100, le=4000, description="Max dimension in pixels"),
    format: Optional[str] = Query(None, description="Target format: jpeg, webp, png"),
    quality: Optional[int] = Query(None, ge=1, le=100, description="Compression quality"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Any:
    """
    Download a poster file, optionally with image processing.

    When no processing params are provided, serves the raw file.
    When size, format, or quality are specified, processes the image
    before serving.

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

        # Resolve to a real path to prevent path traversal
        full_path = os.path.realpath(raw_path)

        if not os.path.exists(full_path):
            return error(
                "Poster file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        # No processing requested — serve raw file
        if size is None and format is None and quality is None:
            return FileResponse(full_path)

        # Process the image before serving
        from PIL import Image
        import tempfile

        format_map = {"jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP", "png": "PNG"}
        pil_format = format_map.get((format or "").lower(), "JPEG")
        ext_map = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}
        target_ext = ext_map.get(pil_format, ".jpg")
        media_types = {"JPEG": "image/jpeg", "WEBP": "image/webp", "PNG": "image/png"}

        with Image.open(full_path) as img:
            if size:
                img.thumbnail((size, size), Image.LANCZOS)
            if pil_format in ("JPEG",):
                img = img.convert("RGB")

            tmp = tempfile.NamedTemporaryFile(suffix=target_ext, delete=False)
            save_kwargs = {"format": pil_format}
            if quality and pil_format in ("JPEG", "WEBP"):
                save_kwargs["quality"] = quality
                save_kwargs["optimize"] = True
            img.save(tmp.name, **save_kwargs)
            tmp.close()

        return FileResponse(
            tmp.name,
            media_type=media_types.get(pil_format, "image/jpeg"),
            filename=f"poster_{poster_id}{target_ext}",
        )

    except Exception as e:
        logger.error(f"Error downloading poster {poster_id}: {e}")
        return error(
            f"Error downloading poster: {str(e)}",
            code="POSTER_DOWNLOAD_ERROR",
            status_code=500,
        )


@router.post(
    "/{poster_id}/sync-metadata",
    summary="Sync poster metadata",
    description="Enqueue a poster_renamerr job for a specific poster by ID.",
    responses={
        200: {
            "description": "Metadata sync job enqueued",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Metadata sync initiated",
                        "data": {"job_id": 123, "poster_id": 1},
                    }
                }
            },
        }
    },
)
async def sync_poster_metadata(
    poster_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Synchronize metadata for a specific poster.

    Enqueues a poster_renamerr job scoped to a single media item.

    Args:
        poster_id: The unique identifier of the poster to sync

    Returns:
        Job ID for tracking the sync operation
    """
    try:
        logger.debug(f"Serving POST /api/posters/{poster_id}/sync-metadata")
        result = db.worker.enqueue_job(
            "jobs",
            {"module_name": "poster_renamerr", "media_ids": [poster_id]},
            job_type="module_run",
        )
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok("Metadata sync initiated", {"job_id": job_id, "poster_id": poster_id})
        return error(
            "Error enqueuing metadata sync",
            code="METADATA_SYNC_ERROR",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error syncing poster metadata for {poster_id}: {e}")
        return error(
            f"Error syncing poster metadata: {str(e)}",
            code="METADATA_SYNC_ERROR",
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

    Removes the poster record from the database, optionally
    deletes the physical file, records it as orphaned, and
    marks any associated media items as unmatched.

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
        try:
            body = await request.json()
            delete_file = body.get("deleteFile", delete_file)
        except Exception:
            pass

        record = db.poster.delete_by_integer_id(poster_id)
        if not record:
            return error("Poster not found", code="POSTER_NOT_FOUND", status_code=404)

        # Optionally delete file from disk
        file_path = record.get("file")
        folder = record.get("folder")
        full_path = (
            os.path.join(folder, file_path) if folder and file_path else file_path
        )
        if delete_file and full_path and os.path.exists(full_path):
            os.remove(full_path)
            logger.info(f"Deleted poster file: {full_path}")

        # Record as orphaned poster for tracking (scoped to configured roots so
        # the table doesn't accumulate rows that the cleanup pass would reject).
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        orphan_path = full_path or file_path
        try:
            from backend.util.config import load_config
            from backend.util.path_safety import get_allowed_roots
            from backend.util.database.orphaned_posters import _path_under_any_root

            cfg = load_config()
            allowed_roots = [str(r) for r in get_allowed_roots(cfg)]
            if allowed_roots and not _path_under_any_root(orphan_path, allowed_roots):
                logger.debug(
                    f"[SKIPPED out-of-scope orphan insert] {orphan_path}"
                )
            else:
                db.orphaned.execute_query(
                    """
                    INSERT OR IGNORE INTO orphaned_posters
                        (asset_type, title, year, season, file_path, date_orphaned)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "poster",
                        record.get("title"),
                        record.get("year"),
                        record.get("season_number"),
                        orphan_path,
                        now,
                    ),
                )
        except Exception as orphan_err:
            logger.debug(f"Could not record orphaned poster: {orphan_err}")

        # Mark associated media items as unmatched
        unmatched_count = 0
        poster_title = record.get("normalized_title")
        if poster_title:
            try:
                # Find media items that were matched to this poster by original_file
                if full_path:
                    media_items = (
                        db.media.execute_query(
                            "SELECT id, title, instance_name, asset_type, year, season_number FROM media_cache WHERE original_file LIKE ?",
                            (f"%{os.path.basename(full_path)}%",),
                            fetch_all=True,
                        )
                        or []
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
                "file_deleted": delete_file,
                "media_unmatched": unmatched_count,
            },
        )
    except Exception as e:
        logger.error(f"Error deleting poster {poster_id}: {e}")
        return error(
            f"Error deleting poster: {str(e)}",
            code="POSTER_DELETE_ERROR",
            status_code=500,
        )

