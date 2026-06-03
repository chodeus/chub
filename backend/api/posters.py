"""
Poster management API endpoints for CHUB.

Provides poster operations including statistics, file management,
upload operations, and directory analysis functionality.
"""

import datetime
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.api.utils import error, get_database, get_logger, get_module_logger, ok
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


def get_cleanarr_logger(request: Request) -> Any:
    """FastAPI dependency: module-dedicated logger for `/plex-metadata/*` calls.

    Routes UI-triggered scans, deletes, and set-active into
    `logs/poster_cleanarr/poster_cleanarr.log` so every user action the
    Poster Cleanarr page takes leaves an audit trail in the module's log —
    not just scheduled module runs.
    """
    return get_module_logger(request, "poster_cleanarr")


# --- New endpoints: search, stats, browse, collections ---


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
        collections = (
            db.poster.execute_query(
                "SELECT * FROM poster_collections ORDER BY name", fetch_all=True
            )
            or []
        )

        # Hydrate each collection with its poster contents + count. One join
        # per collection is fine — the table is small and rarely fetched.
        for col in collections:
            posters = (
                db.poster.execute_query(
                    """
                SELECT p.id, p.asset_type, p.title, p.year, p.season_number,
                       p.folder, p.file, p.style
                FROM poster_collection_items pci
                JOIN poster_cache p ON p.id = pci.poster_id
                WHERE pci.collection_id = ?
                ORDER BY p.title
                """,
                    (col["id"],),
                    fetch_all=True,
                )
                or []
            )
            col["posters"] = posters
            col["poster_count"] = len(posters)

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
        result["owners"] = db.poster.get_distinct_owners()
        # Merge styles already stamped on rows with styles derivable from the
        # current gdrive_list config so the dropdown is useful even before
        # poster_renamerr has re-upserted existing rows with the new column.
        db_styles = set(db.poster.get_distinct_styles())
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
        except Exception as e:
            logger.debug(f"Could not derive configured styles from config: {e}")
        result["styles"] = sorted(db_styles | configured_styles)
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
            return error(
                "Field 'name' is required", code="MISSING_NAME", status_code=400
            )

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
        logger.debug(
            f"Serving DELETE /api/posters/collections/{collection_id}/remove/{poster_id}"
        )

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


@router.delete(
    "/collections/{collection_id}",
    summary="Delete poster collection",
    description="Delete a poster collection and all of its membership rows. "
    "The underlying poster files are not touched.",
)
async def delete_poster_collection(
    collection_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug(f"Serving DELETE /api/posters/collections/{collection_id}")

        existing = db.poster.execute_query(
            "SELECT id FROM poster_collections WHERE id=?",
            (collection_id,),
            fetch_one=True,
        )
        if not existing:
            return error(
                f"Poster collection {collection_id} not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        db.poster.execute_query(
            "DELETE FROM poster_collection_items WHERE collection_id=?",
            (collection_id,),
        )
        db.poster.execute_query(
            "DELETE FROM poster_collections WHERE id=?", (collection_id,)
        )

        return ok(
            "Poster collection deleted",
            {"collection_id": collection_id},
        )

    except Exception as e:
        logger.error(f"Error deleting poster collection: {e}")
        return error(
            f"Error deleting poster collection: {str(e)}",
            code="POSTER_COLLECTION_DELETE_ERROR",
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

    # The full-cache read + per-poster PIL resize/convert loop is heavy and
    # CPU-bound; run it off the event loop so it doesn't freeze the server.
    return await run_in_threadpool(
        _optimize_posters_sync,
        db,
        logger,
        max_width,
        max_height,
        pil_format,
        target_ext,
        quality,
        mode,
    )


def _optimize_posters_sync(
    db,
    logger,
    max_width,
    max_height,
    pil_format,
    target_ext,
    quality,
    mode,
) -> JSONResponse:
    """Blocking body of optimize_posters — runs in a worker thread."""
    from PIL import Image

    try:
        # Get all posters from cache
        posters = db.poster.get_all()
        if not posters:
            return ok(
                "No posters found to optimize",
                {
                    "processed": 0,
                    "skipped": 0,
                    "failed": 0,
                    "bytes_saved": 0,
                    "mode": mode,
                },
            )

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
                        details.append(
                            {
                                "file": full_path,
                                "size": original_size,
                                "dimensions": f"{w}x{h}",
                                "needs_resize": needs_resize,
                                "needs_convert": needs_convert,
                            }
                        )
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
            f"Error retrieving unmatched assets details: {str(e)}",
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
            f"Error retrieving unmatched artwork: {str(e)}",
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
    allowed = {"logo", "background", "squareart"}
    if image_type not in allowed:
        return error(
            f"image_type must be one of {sorted(allowed)}, got '{image_type}'",
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
        logger.error(
            f"Error updating artwork ignore for {media_id}/{image_type}: {e}"
        )
        return error(
            f"Error updating artwork ignore flag: {str(e)}",
            code="ARTWORK_IGNORE_ERROR",
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
        iface.set_ignored(media_id, ignored)
        # Ignoring releases any manual-pick lock so the matcher is free to
        # re-evaluate the row (it's hidden from review while ignored anyway).
        if ignored:
            iface.set_user_confirmed(media_id, False)
        verb = "ignored" if ignored else "restored"
        return ok(f"Row {verb}", {"id": media_id, "ignored": bool(ignored)})
    except Exception as e:
        logger.error(f"Error updating ignore flag for {media_id}: {e}")
        return error(
            f"Error updating ignore flag: {str(e)}",
            code="MATCH_IGNORE_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/approve",
    summary="Approve a needs-review match",
    description="Confirm a needs-review media/collection row, promoting it to "
    "the 'matched' state and clearing any conflict flags.",
)
async def approve_match(
    media_id: int,
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Mark a reviewed row as confidently matched."""
    try:
        logger.debug(f"Serving POST /api/posters/match/{media_id}/approve (kind={kind})")
        table = "collections_cache" if kind == "collection" else "media_cache"
        iface = db.collection if kind == "collection" else db.media
        iface.execute_query(
            f"UPDATE {table} SET match_status='matched', match_confidence=1.0, "
            "conflict_ids='[]' WHERE id=?",
            (media_id,),
        )
        # Lock the confirmed match so a future re-scan can't revert it (Fix B).
        iface.set_user_confirmed(media_id, True)
        return ok("Match approved", {"id": media_id, "match_status": "matched"})
    except Exception as e:
        logger.error(f"Error approving match for {media_id}: {e}")
        return error(
            f"Error approving match: {str(e)}",
            code="MATCH_APPROVE_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/unlock",
    summary="Unlock a confirmed match and re-open it for review",
    description="Clear the user_confirmed lock on a media/collection row and put "
    "it back into the 'needs_review' queue so the matcher can recompute it (or the "
    "user can re-pick) on the next run.",
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
        table = "collections_cache" if kind == "collection" else "media_cache"
        iface = db.collection if kind == "collection" else db.media
        iface.execute_query(
            f"UPDATE {table} SET match_status='needs_review' WHERE id=?",
            (media_id,),
        )
        # Drop the lock so the next scheduled run is free to recompute the match.
        iface.set_user_confirmed(media_id, False)
        return ok(
            "Match unlocked",
            {"id": media_id, "match_status": "needs_review"},
        )
    except Exception as e:
        logger.error(f"Error unlocking match for {media_id}: {e}")
        return error(
            f"Error unlocking match: {str(e)}",
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
        import json as _json

        import difflib

        from backend.util.helper import is_match
        from backend.util.normalization import normalize_titles

        row = (
            db.collection.get_by_id(media_id)
            if kind == "collection"
            else db.media.get_by_id(media_id)
        )
        if not row:
            return error("Media row not found", code="NOT_FOUND", status_code=404)

        asset_type = "collection" if kind == "collection" else row.get("asset_type")
        season_number = row.get("season_number")
        try:
            alts = _json.loads(row.get("alternate_titles") or "[]")
        except (ValueError, TypeError):
            alts = []
        search_titles = [row.get("title")] + [a for a in alts if a]
        row_norm = row.get("normalized_title") or normalize_titles(row.get("title") or "")

        seen = set()
        gathered = []
        for st in search_titles:
            for c in db.poster.get_candidates_by_prefix(
                st or "", asset_type=asset_type
            ):
                f = c.get("file")
                if f and f not in seen:
                    seen.add(f)
                    gathered.append(c)
                if len(gathered) >= 800:  # bound the pool before scoring
                    break

        # Score every candidate by title similarity. The prefix bucket alone is
        # NOT relevance — without this, the picker showed every poster sharing
        # the first 3 chars ("str" → Striptease, Strays, …) regardless of the
        # title. Rank real matches first, then by similarity, and drop posters
        # that neither match nor resemble the title.
        scored = []
        for c in gathered:
            cs = c.get("season_number")
            if season_number is not None and cs != season_number:
                continue
            if season_number is None and cs is not None:
                continue
            matched, reason = is_match(c, row)
            sim = difflib.SequenceMatcher(
                None, row_norm, c.get("normalized_title") or ""
            ).ratio()
            scored.append((bool(matched), sim, c, reason))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        candidates = []
        for matched, sim, c, reason in scored:
            # Real matches always show; non-matching extras only if the title
            # genuinely resembles (drops same-prefix-but-unrelated noise).
            if not matched and sim < 0.6:
                continue
            candidates.append(
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
            )
            if len(candidates) >= limit:
                break

        return ok(
            f"{len(candidates)} candidate posters",
            {
                "candidates": candidates,
                "media": {
                    "title": row.get("title"),
                    "year": row.get("year"),
                    "season_number": season_number,
                    "type": asset_type,
                },
            },
        )
    except Exception as e:
        logger.error(f"Error fetching match candidates for {media_id}: {e}")
        return error(
            f"Error fetching candidates: {str(e)}",
            code="MATCH_CANDIDATES_ERROR",
            status_code=500,
        )


@router.post(
    "/match/{media_id}/apply",
    summary="Manually apply a chosen poster to a media row",
    description="Link a specific poster to a media/collection row and copy it "
    "to the destination. Used by the manual poster picker.",
)
def apply_match(
    media_id: int,
    poster_id: int = Query(...),
    kind: str = Query("media", pattern="^(media|collection)$"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
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
        poster = db.poster.execute_query(
            "SELECT * FROM poster_cache WHERE id=?", (poster_id,), fetch_one=True
        )
        if not poster:
            return error("Poster not found", code="NOT_FOUND", status_code=404)

        pfile = poster.get("file")
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
            f"Error applying poster: {str(e)}",
            code="MATCH_APPLY_ERROR",
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

        # All "sync gdrive" UI actions go through the canonical
        # module_run path — same job_type, same processor, same
        # SyncGDrive.run() method — with optional kwargs steering the
        # behavior:
        #   selecting all configured → no module_args (run all, notify)
        #   selecting a subset       → only_folders=[...] + notify
        #   selecting one            → only_folders=[name] + notify=False
        #                              (UI toast is the user's feedback;
        #                               a Discord ping per click is noise)
        syncer = SyncGDrive(logger=gdrive_logger)
        configured = {
            item.name
            for item in (
                syncer.config.gdrive_list
                if isinstance(syncer.config.gdrive_list, list)
                else [syncer.config.gdrive_list]
            )
        }

        requested = set(gdrive_names)
        is_full_set = bool(configured) and requested == configured
        is_single = len(requested) == 1

        payload: Dict[str, Any] = {
            "module_name": "sync_gdrive",
            "origin": "web",
        }
        if not is_full_set:
            payload["module_args"] = {
                "only_folders": list(gdrive_names),
                "notify": not is_single,
            }

        job_result = db.worker.enqueue_job(
            "jobs", payload=payload, job_type="module_run"
        )
        job_id = job_result.get("data", {}).get("job_id")

        if is_full_set:
            return ok(
                f"GDrive sync started for all {len(configured)} folders",
                {"job_id": job_id, "scope": "all"},
            )
        if is_single:
            only = next(iter(requested))
            return ok(
                f"GDrive sync started for '{only}'",
                {"job_id": job_id, "name": only, "scope": "single"},
            )
        return ok(
            f"GDrive sync started for {len(requested)} folders: "
            f"{', '.join(sorted(requested))}",
            {
                "job_id": job_id,
                "queued_count": len(requested),
                "scope": "subset",
            },
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
                location = getattr(config.poster_renamerr, "destination_dir", None)
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

        # Restrict the served file to configured allowed roots — otherwise
        # an authenticated caller could point at arbitrary dirs (/etc, /root).
        from backend.util.config import load_config
        from backend.util.path_safety import is_path_allowed

        try:
            config = load_config()
        except Exception:  # noqa: S110 — fail closed below
            config = None

        if config is None:
            return error(
                "Access denied - path outside allowed directory",
                code="PATH_TRAVERSAL_DENIED",
                status_code=403,
            )

        path_obj = Path(path)
        if path_obj.is_absolute():
            # Frontend already gave us a concrete absolute path (e.g. the
            # Assets Search grid passes item.file straight through, with
            # item.folder in location as an owner label, not a root).
            # Validate the file path itself against allowed roots instead
            # of demanding that `location` is a root.
            if not is_path_allowed(path, config):
                return error(
                    "Access denied - path outside allowed directory",
                    code="PATH_TRAVERSAL_DENIED",
                    status_code=403,
                )
            file_path = path_obj.resolve()
        else:
            # Relative path — `location` must be an allowed root and the
            # resolved result must stay inside it (is_relative_to avoids
            # the str.startswith bypass where `/posters_evil/x` slipped
            # past a `/posters` prefix).
            if not is_path_allowed(location, config):
                return error(
                    "Access denied - path outside allowed directory",
                    code="PATH_TRAVERSAL_DENIED",
                    status_code=403,
                )
            base_dir = Path(location).resolve()
            file_path = (base_dir / path).resolve()
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
        rows = (
            db.worker.execute_query(
                "SELECT id, file FROM poster_cache WHERE width IS NULL OR height IS NULL "
                "LIMIT ?",
                (limit,),
                fetch_all=True,
            )
            or []
        )

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
            f"Error listing recently matched posters: {str(e)}",
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
            f"Error listing applied media: {str(e)}",
            code="APPLIED_MEDIA_ERROR",
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
    media_type: str = Query(
        "all",
        description="Filter by metadata_type label: movie, show, season, episode, artist, album, collection, all.",
    ),
    library_id: int = Query(
        0, description="Filter by Plex library_section_id. 0 = all."
    ),
    variant_kind: str = Query(
        "all",
        description="Filter to variants of a single kind (poster/art/banner/thumb/chapter/theme/other). Bundles with no matching variants are hidden.",
    ),
    force: bool = Query(False, description="Bypass the 5-min scan cache"),
    logger: Any = Depends(get_cleanarr_logger),
):
    """
    Group Plex Metadata poster variants by their owning media item.

    Returns `{bundles, libraries, total, limit, offset, stats}`. Filters are
    applied *after* the scan (so the scan + cache is reusable across filter
    combinations). `libraries` lists every section that has at least one
    bundle in the unfiltered scan so the frontend can render a dropdown.
    """
    try:
        import time as _time

        from backend.util.plex_metadata import scan_bundles, scan_transcoder_cache

        plex_path = _get_plex_path(request)
        if not plex_path:
            logger.error("Scan requested but plex_path is not configured")
            return error(
                "Plex path is not configured",
                code="PLEX_PATH_UNSET",
                status_code=400,
            )
        logger.info(
            f"UI scan requested: media_type={media_type} library_id={library_id} "
            f"variant_kind={variant_kind} only_bloat={only_bloat} force={force}"
        )
        _t0 = _time.time()
        scan = scan_bundles(plex_path, force=force)
        transcoder = scan_transcoder_cache(plex_path, force=force)
        logger.info(
            f"UI scan complete in {_time.time() - _t0:.1f}s — "
            f"{scan['stats']['bundle_count']} bundles, "
            f"{scan['stats']['variant_count']} variants, "
            f"{scan['stats']['bloat_count']} bloat, "
            f"transcoder cache {transcoder['count']} files / {transcoder['size_bytes']} bytes"
        )
        bundles = scan["bundles"]

        media_type = (media_type or "all").lower()
        variant_kind = (variant_kind or "all").lower()

        if media_type != "all":
            bundles = [
                b for b in bundles if (b.get("metadata_type_label") or "") == media_type
            ]
        if library_id:
            bundles = [b for b in bundles if b.get("library_section_id") == library_id]
        if variant_kind != "all":
            trimmed = []
            for b in bundles:
                kept = [v for v in b["variants"] if v.get("kind") == variant_kind]
                if kept:
                    trimmed.append({**b, "variants": kept})
            bundles = trimmed
        if only_bloat:
            bundles = [
                b for b in bundles if any(not v["active"] for v in b["variants"])
            ]
        total = len(bundles)
        page = bundles[offset : offset + limit]
        return ok(
            f"Retrieved {len(page)} of {total} bundles",
            {
                "bundles": page,
                "libraries": scan.get("libraries", []),
                "media_types": scan.get("media_types", []),
                "variant_kinds": scan.get("variant_kinds", []),
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": scan["stats"],
                "transcoder": transcoder,
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
    logger: Any = Depends(get_cleanarr_logger),
):
    """Flat list of bloat variants across all bundles, largest first."""
    try:
        from backend.util.plex_metadata import get_bloat_flat, scan_bundles

        plex_path = _get_plex_path(request)
        if not plex_path:
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
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
    logger: Any = Depends(get_cleanarr_logger),
):
    """
    Enqueue a `poster_cleanarr` job. Request body:
        {
          "mode": "report" | "move" | "remove",          # bloat-image mode
          "target_paths": [str, ...],                    # optional bloat subset
          "orphan_assets_enabled": bool,                 # optional, default config value
          "orphan_assets_mode": "report"|"move"|"remove",
          "asset_dirs": [str, ...]                       # optional override
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
            return error(f"Invalid mode '{mode}'", code="INVALID_MODE", status_code=400)
        overrides: dict = {"mode": mode}

        target_paths = body.get("target_paths")
        if isinstance(target_paths, list) and target_paths:
            overrides["target_paths"] = [str(p) for p in target_paths]

        if "orphan_assets_enabled" in body:
            overrides["orphan_assets_enabled"] = bool(body.get("orphan_assets_enabled"))
        orphan_mode = body.get("orphan_assets_mode")
        if isinstance(orphan_mode, str):
            orphan_mode = orphan_mode.lower()
            if orphan_mode not in ("report", "move", "remove"):
                return error(
                    f"Invalid orphan_assets_mode '{orphan_mode}'",
                    code="INVALID_MODE",
                    status_code=400,
                )
            overrides["orphan_assets_mode"] = orphan_mode
        asset_dirs = body.get("asset_dirs")
        if isinstance(asset_dirs, list):
            overrides["asset_dirs"] = [str(p) for p in asset_dirs]

        payload = {
            "module_name": "poster_cleanarr",
            "overrides": overrides,
        }

        result = db.worker.enqueue_job("jobs", payload, job_type="module_run")
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(
                f"Poster cleanarr cleanup enqueued (mode={mode}, job_id={job_id})"
            )
            return ok("Cleanup job enqueued", {"job_id": job_id, "mode": mode})
        return error(
            "Failed to enqueue cleanup", code="ENQUEUE_FAILED", status_code=500
        )
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
    logger: Any = Depends(get_cleanarr_logger),
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
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        ok_ = delete_variant(path, plex_path=plex_path)
        if not ok_:
            logger.warning(
                f"UI delete rejected (outside metadata or I/O error): {path}"
            )
            return error(
                "Failed to delete variant (path outside Plex metadata or I/O error)",
                code="VARIANT_DELETE_FAILED",
                status_code=400,
            )
        logger.info(f"UI delete: {path}")
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
    logger: Any = Depends(get_cleanarr_logger),
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
            return error(
                "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
            )
        metadata_dir = os.path.realpath(os.path.join(plex_path, "Metadata"))
        safe_path = os.path.realpath(path)
        if not safe_path.startswith(metadata_dir + os.sep):
            return error(
                "Path outside Plex metadata dir", code="INVALID_PATH", status_code=400
            )
        if not os.path.isfile(safe_path):
            return error(
                "Variant file not found on disk", code="FILE_NOT_FOUND", status_code=404
            )

        from backend.util.config import load_config

        cfg = load_config()
        # Pick the first configured Plex instance — CHUB typically has one.
        plex_instances = getattr(getattr(cfg, "instances", None), "plex", None) or {}
        instance_cfg = (
            next(iter(plex_instances.values()), None) if plex_instances else None
        )
        if instance_cfg is None:
            return error(
                "No Plex instance configured",
                code="NO_PLEX_INSTANCE",
                status_code=400,
            )

        from plexapi.server import PlexServer
        from plexapi.exceptions import NotFound

        # The Plex connect + fetch + upload is blocking — run it off the event
        # loop. fetchItem raises NotFound (never returns None) on a bad rating
        # key, so catch that and return a 404 instead of falling through to the
        # broad handler's 500 (the old `is None` check was dead).
        def _apply_active():
            server = PlexServer(instance_cfg.url, instance_cfg.api)
            try:
                item = server.fetchItem(int(rating_key))
            except NotFound:
                return False
            item.uploadPoster(filepath=safe_path)
            return True

        applied = await run_in_threadpool(_apply_active)
        if not applied:
            return error("Plex item not found", code="ITEM_NOT_FOUND", status_code=404)
        invalidate_cache()
        logger.info(f"UI set-active: rating_key={rating_key} path={safe_path}")
        return ok(
            "Active poster updated", {"rating_key": rating_key, "path": safe_path}
        )
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
        return error(
            "Plex path is not configured", code="PLEX_PATH_UNSET", status_code=400
        )
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
