"""
Media management API endpoints for CHUB.

Provides media search, statistics, collections, and management
operations against the media cache database including metadata
fixes, duplicate detection, import/export, and ARR integration.
"""

import csv
import io
import os
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.arr import create_arr_client
from backend.util.config import load_config
from backend.util.database import ChubDB

router = APIRouter(
    prefix="/api/media",
    tags=["Media"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Media item not found"},
    },
)


# --- Static path endpoints (must be declared before /{mediaId}) ---


@router.get(
    "/search",
    summary="Search media library",
    description="Search and filter media items with full-text query, genre, year, "
    "rating, instance, and matched-status filters. Supports pagination and sorting.",
    responses={
        200: {
            "description": "Search results returned successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 42 media items",
                        "data": {
                            "items": [
                                {
                                    "id": 1,
                                    "title": "The Matrix",
                                    "year": 1999,
                                    "rating": "8.7",
                                    "instance_name": "radarr",
                                }
                            ],
                            "total": 42,
                            "limit": 50,
                            "offset": 0,
                        },
                    }
                }
            },
        }
    },
)
async def search_media(
    query: Optional[str] = None,
    type: Optional[str] = Query(
        None, description="Filter by asset type: movie, show, all"
    ),
    genres: Optional[List[str]] = Query(None, description="Filter by genres"),
    year_min: Optional[int] = Query(None, alias="year_min"),
    year_max: Optional[int] = Query(None, alias="year_max"),
    rating_min: Optional[float] = Query(
        None, alias="rating_min", description="Minimum rating (inclusive)"
    ),
    rating_max: Optional[float] = Query(
        None, alias="rating_max", description="Maximum rating (inclusive)"
    ),
    instance: Optional[str] = Query(None, description="Filter by instance name"),
    matched: Optional[int] = Query(
        None, description="Filter by matched status: 0 or 1"
    ),
    sort: str = Query("title", description="Sort field: title, year, rating"),
    order: str = Query("asc", description="Sort order: asc, desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Search and filter media items with pagination.

    Performs a full-text search against normalised and raw titles,
    then applies optional filters for asset type, genres, year range,
    rating range, instance, and matched status.

    Args:
        query: Free-text search string matched against title fields
        type: Asset type filter (movie, show, or all)
        genres: List of genre strings to match (OR logic)
        year_min: Minimum release year (inclusive)
        year_max: Maximum release year (inclusive)
        rating_min: Minimum rating value (inclusive, cast from text)
        rating_max: Maximum rating value (inclusive, cast from text)
        instance: Instance name to restrict results to
        matched: Matched status flag (0 or 1)
        sort: Column to sort by (title, year, rating)
        order: Sort direction (asc or desc)
        limit: Maximum items per page (1-500)
        offset: Number of items to skip

    Returns:
        Paginated list of matching media items with total count
    """
    try:
        logger.debug(f"Serving GET /api/media/search query={query}")

        result = db.media.search(
            query=query,
            asset_type=type,
            genres=genres,
            year_min=year_min,
            year_max=year_max,
            rating_min=rating_min,
            rating_max=rating_max,
            instance_name=instance,
            matched=matched,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )

        return ok(f"Found {result['total']} media items", result)

    except Exception as e:
        logger.error(f"Error searching media: {e}")
        return error(
            f"Error searching media: {str(e)}",
            code="MEDIA_SEARCH_ERROR",
            status_code=500,
        )


@router.get(
    "/stats",
    summary="Get media statistics",
    description="Retrieve aggregate statistics from the media cache, "
    "optionally filtered by asset type.",
    responses={
        200: {
            "description": "Media statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media statistics retrieved",
                        "data": {
                            "by_type": [
                                {
                                    "asset_type": "movie",
                                    "total": 500,
                                    "matched": 480,
                                    "instances": 2,
                                }
                            ],
                            "total": 750,
                            "matched": 700,
                            "unmatched": 50,
                        },
                    }
                }
            },
        }
    },
)
async def get_media_stats(
    type: Optional[str] = Query(None, description="Filter by asset type"),
    period: Optional[str] = Query(
        None,
        description="Time window for stats: '7d', '30d', '90d'. "
        "Requires created_at column in media_cache.",
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get aggregate statistics from the media cache.

    Returns counts grouped by asset type as well as overall totals
    for matched, unmatched, and instance breakdowns.

    When `period` is specified, only counts items added within that
    time window (requires created_at column in media_cache table).

    Args:
        type: Optional asset type filter (movie, show, or all)
        period: Optional time window (7d, 30d, 90d)

    Returns:
        Statistics object with per-type and overall counts
    """
    try:
        logger.debug("Serving GET /api/media/stats")

        # Parse period into days
        period_days = None
        if period:
            period_map = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
            period_days = period_map.get(period)

        stats = db.media.get_stats(asset_type=type, period_days=period_days)

        return ok("Media statistics retrieved", stats)

    except Exception as e:
        logger.error(f"Error retrieving media stats: {e}")
        return error(
            f"Error retrieving media stats: {str(e)}",
            code="MEDIA_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/stats/detailed",
    summary="Get detailed media statistics",
    description="Retrieve extended statistics with breakdowns by instance, status, "
    "language, rating, studio, decade, genre, runtime, and monitored status.",
)
async def get_media_stats_detailed(
    type: Optional[str] = Query(None, description="Filter by asset type"),
    period: Optional[str] = Query(
        None,
        description="Time window: '7d', '30d', '90d', '1y'.",
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Get extended media statistics with multiple dimension breakdowns."""
    try:
        logger.debug("Serving GET /api/media/stats/detailed")
        period_days = None
        if period:
            period_map = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
            period_days = period_map.get(period)

        stats = db.media.get_detailed_stats(asset_type=type, period_days=period_days)
        return ok("Detailed media statistics retrieved", stats)

    except Exception as e:
        logger.error(f"Error retrieving detailed media stats: {e}")
        return error(
            f"Error retrieving detailed media stats: {str(e)}",
            code="MEDIA_STATS_DETAILED_ERROR",
            status_code=500,
        )


@router.get(
    "/genres",
    summary="Get available genres",
    description="Retrieve a sorted list of unique genres extracted "
    "from all media cache entries.",
    responses={
        200: {
            "description": "Genres retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 18 genres",
                        "data": {"genres": ["Action", "Comedy", "Drama", "Sci-Fi"]},
                    }
                }
            },
        }
    },
)
async def get_genres(
    type: Optional[str] = Query(None, description="Filter by asset type"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get a sorted list of unique genres from the media cache.

    Parses both JSON-array and comma-separated genre strings,
    deduplicates them, and returns a sorted list.

    Args:
        type: Optional asset type filter (movie, show, or all)

    Returns:
        Sorted list of unique genre strings
    """
    try:
        logger.debug("Serving GET /api/media/genres")

        genres = db.media.get_distinct_genres(asset_type=type)

        return ok(f"Found {len(genres)} genres", {"genres": genres})

    except Exception as e:
        logger.error(f"Error retrieving genres: {e}")
        return error(
            f"Error retrieving genres: {str(e)}",
            code="GENRES_ERROR",
            status_code=500,
        )


@router.get(
    "/collections",
    summary="Get media collections",
    description="Retrieve all collections from the collection cache.",
    responses={
        200: {
            "description": "Collections retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 25 collections",
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
async def get_collections(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get all collections from the collection cache.

    Returns the complete list of synced collections with their
    metadata and identifiers.

    Returns:
        List of collection objects
    """
    try:
        logger.debug("Serving GET /api/media/collections")

        collections = db.collection.get_all()

        return ok(
            f"Retrieved {len(collections)} collections", {"collections": collections}
        )

    except Exception as e:
        logger.error(f"Error retrieving collections: {e}")
        return error(
            f"Error retrieving collections: {str(e)}",
            code="COLLECTIONS_ERROR",
            status_code=500,
        )


@router.get(
    "/duplicates",
    summary="Find duplicate media",
    description="Identify media items that share the same title and year "
    "across different instances.",
    responses={
        200: {
            "description": "Duplicate groups returned successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Found 5 duplicate groups",
                        "data": {
                            "duplicates": [
                                {
                                    "normalized_title": "the matrix",
                                    "year": 1999,
                                    "count": 2,
                                    "ids": "1,42",
                                    "instances": "radarr,radarr4k",
                                }
                            ],
                            "total": 5,
                        },
                    }
                }
            },
        }
    },
)
async def get_duplicates(
    type: Optional[str] = Query(None, description="Filter by asset type"),
    similarity: Optional[float] = Query(
        None, ge=0.0, le=1.0,
        description="Fuzzy match threshold (0-1). When set, uses title similarity "
        "instead of exact match. 0.8 = 80% similar."
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Find duplicate media entries WITHIN a single ARR instance.

    A duplicate is two or more entries from the same instance sharing
    the same (normalized_title, year). The same title appearing in
    different instances (e.g. Radarr + Radarr4K) is intentional quality
    coverage and is not reported.

    When `similarity` is provided, uses fuzzy title matching with
    difflib.SequenceMatcher instead of exact normalized-title match,
    still restricted to within-instance comparisons.

    Args:
        type: Optional asset type filter (movie, show, or all)
        similarity: Optional fuzzy match threshold (0.0-1.0)

    Returns:
        List of duplicate groups with item IDs and the offending instance
    """
    try:
        logger.debug("Serving GET /api/media/duplicates")

        if similarity is not None:
            # Fuzzy matching: group by similarity WITHIN the same instance.
            # Cross-instance matches are intentional quality coverage and
            # are not reported as duplicates.
            from difflib import SequenceMatcher

            all_media = [
                m for m in db.media.get_all(asset_type=type)
                if m.get("season_number") is None
            ]
            groups = []
            used = set()

            for i, item_a in enumerate(all_media):
                if i in used:
                    continue
                title_a = (item_a.get("normalized_title") or item_a.get("title", "")).lower()
                year_a = item_a.get("year")
                instance_a = item_a.get("instance_name")
                group = [item_a]

                for j, item_b in enumerate(all_media):
                    if j <= i or j in used:
                        continue
                    # Must be same instance — cross-instance isn't a dupe
                    if item_b.get("instance_name") != instance_a:
                        continue
                    title_b = (item_b.get("normalized_title") or item_b.get("title", "")).lower()
                    year_b = item_b.get("year")

                    # Year must match (or both be None)
                    if year_a != year_b:
                        continue

                    ratio = SequenceMatcher(None, title_a, title_b).ratio()
                    if ratio >= similarity:
                        group.append(item_b)
                        used.add(j)

                if len(group) > 1:
                    used.add(i)
                    groups.append({
                        "normalized_title": title_a,
                        "year": year_a,
                        "instance_name": instance_a,
                        "count": len(group),
                        "ids": ",".join(str(g.get("id", "")) for g in group),
                        "instances": ",".join(g.get("instance_name", "") for g in group),
                        "similarity": round(min(
                            SequenceMatcher(None, title_a,
                                (g.get("normalized_title") or g.get("title", "")).lower()
                            ).ratio()
                            for g in group[1:]
                        ), 2),
                    })

            duplicates = groups
        else:
            duplicates = db.media.find_duplicates(asset_type=type)

        # Filter out groups where all instances belong to the same
        # quality group (configured in general.duplicate_exclude_groups).
        # e.g. [["radarr", "radarr4k"]] means radarr+radarr4k pairs
        # are intentional quality copies, not real duplicates.
        try:
            from backend.util.config import load_config
            raw_groups = load_config().general.duplicate_exclude_groups
            if raw_groups:
                # Normalise: accept both [["a","b"]] and [{"instances":["a","b"]}]
                exclude_sets = []
                for g in raw_groups:
                    if isinstance(g, dict):
                        exclude_sets.append(set(g.get("instances", [])))
                    else:
                        exclude_sets.append(set(g))
                exclude_sets = [s for s in exclude_sets if len(s) >= 2]

                if exclude_sets:
                    filtered = []
                    for dup in duplicates:
                        raw = dup.get("instances", "")
                        instances = {s.strip() for s in raw.split(",") if s.strip()}
                        in_same_group = any(
                            instances.issubset(group) for group in exclude_sets
                        )
                        if not in_same_group:
                            filtered.append(dup)
                    duplicates = filtered
        except Exception:
            pass  # Config not loaded — skip filtering

        return ok(
            f"Found {len(duplicates)} duplicate groups",
            {"duplicates": duplicates, "total": len(duplicates)},
        )

    except Exception as e:
        logger.error(f"Error finding duplicates: {e}")
        return error(
            f"Error finding duplicates: {str(e)}",
            code="DUPLICATES_ERROR",
            status_code=500,
        )


@router.post(
    "/refresh",
    summary="Refresh media cache",
    description="Trigger a background cache refresh job. Accepts both frontend "
    "format (path, deep) and backend format (arr_instances, plex_instances, "
    "libraries, update_mappings).",
    responses={
        200: {
            "description": "Cache refresh job enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media refresh initiated",
                        "data": {"job_id": 123},
                    }
                }
            },
        }
    },
)
async def refresh_media(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Trigger a background cache refresh job.

    Accepts two payload formats:
    - Frontend format: ``path`` and ``deep`` keys trigger a full
      refresh of all configured instances.
    - Backend format: ``arr_instances``, ``plex_instances``,
      ``libraries``, and ``update_mappings`` for targeted refresh.

    Returns:
        Job ID for tracking the refresh operation
    """
    try:
        try:
            payload = (
                await request.json()
                if request.headers.get("content-type") == "application/json"
                else {}
            )
        except Exception:
            payload = {}
        logger.debug(f"Serving POST /api/media/refresh with payload: {payload}")

        # Frontend sends {path, deep} -- treat as refresh-all
        if "path" in payload or "deep" in payload:
            job_payload = {
                "arr_instances": [],
                "plex_instances": [],
                "libraries": [],
                "update_mappings": True,
            }
        else:
            job_payload = {
                "arr_instances": payload.get("arr_instances", []),
                "plex_instances": payload.get("plex_instances", []),
                "libraries": payload.get("libraries", []),
                "update_mappings": payload.get("update_mappings", False),
            }

        result = db.worker.enqueue_job("jobs", job_payload, job_type="cache_refresh")

        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            logger.info(f"Media refresh job queued: {job_id}")
            return ok("Media refresh initiated", {"job_id": job_id})

        return error(
            f"Error enqueuing refresh: {result.get('message', 'Unknown')}",
            code="MEDIA_REFRESH_ERROR",
            status_code=500,
        )

    except Exception as e:
        logger.error(f"Error serving POST /api/media/refresh: {e}")
        return error(
            f"Error refreshing media: {str(e)}",
            code="MEDIA_REFRESH_ERROR",
            status_code=500,
        )


@router.post(
    "/scan",
    summary="Scan for new media",
    description="Scan for new media by triggering a cache refresh with "
    "optional path filters and recursive flag.",
    responses={
        200: {
            "description": "Scan job enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media scan initiated",
                        "data": {"job_id": 456},
                    }
                }
            },
        }
    },
)
async def scan_media(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Scan for new media by triggering a cache refresh.

    Accepts optional path filters to restrict the scan scope and
    a recursive flag to control directory traversal depth.

    Returns:
        Job ID for tracking the scan operation
    """
    try:
        payload = (
            await request.json()
            if request.headers.get("content-type") == "application/json"
            else {}
        )
        logger.debug("Serving POST /api/media/scan")

        job_payload = {
            "paths": payload.get("paths", []),
            "recursive": payload.get("recursive", True),
        }

        result = db.worker.enqueue_job("jobs", job_payload, job_type="cache_refresh")

        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok("Media scan initiated", {"job_id": job_id})

        return error(
            "Error enqueuing scan",
            code="MEDIA_SCAN_ERROR",
            status_code=500,
        )

    except Exception as e:
        logger.error(f"Error scanning media: {e}")
        return error(
            f"Error scanning media: {str(e)}",
            code="MEDIA_SCAN_ERROR",
            status_code=500,
        )


@router.post(
    "/export",
    summary="Export media data",
    description="Export media cache data in JSON or CSV format with "
    "optional field selection.",
    responses={
        200: {
            "description": "Media data exported successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media exported",
                        "data": {
                            "format": "json",
                            "count": 150,
                            "data": [{"title": "The Matrix", "year": 1999}],
                        },
                    }
                }
            },
        }
    },
)
async def export_media(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Export media cache data in JSON or CSV format.

    Optionally filter output to specific fields. CSV output returns
    the serialised string in the ``data`` key.

    Returns:
        Exported data with format identifier and item count
    """
    try:
        payload = (
            await request.json()
            if request.headers.get("content-type") == "application/json"
            else {}
        )
        export_format = payload.get("format", "json")
        fields = payload.get("fields")
        logger.debug(f"Serving POST /api/media/export format={export_format}")

        all_media = db.media.get_all()

        if fields:
            all_media = [
                {k: item.get(k) for k in fields if k in item} for item in all_media
            ]

        if export_format == "csv":
            if not all_media:
                return ok("No media to export", {"data": "", "format": "csv"})
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=all_media[0].keys())
            writer.writeheader()
            writer.writerows(all_media)
            return ok(
                "Media exported",
                {"data": output.getvalue(), "format": "csv", "count": len(all_media)},
            )

        return ok(
            "Media exported",
            {"data": all_media, "format": "json", "count": len(all_media)},
        )

    except Exception as e:
        logger.error(f"Error exporting media: {e}")
        return error(
            f"Error exporting media: {str(e)}",
            code="MEDIA_EXPORT_ERROR",
            status_code=500,
        )


@router.post(
    "/import",
    summary="Import media to Radarr/Sonarr",
    description="Add media items to a Radarr or Sonarr instance.",
    responses={
        200: {
            "description": "Import result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Imported 3 items: 2 added, 1 existing",
                        "data": {
                            "added": [{"tmdbId": 550, "title": "Fight Club"}],
                            "existing": [{"tmdbId": 680, "title": "Pulp Fiction"}],
                            "invalid": [],
                            "failed": [],
                        },
                    }
                }
            },
        }
    },
)
async def import_media(
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Import media items to a Radarr or Sonarr instance.

    Validates each item doesn't already exist before adding.
    Supports batch import with per-request feedback.

    Request body (JSON):
        items: List of media objects, each with:
            - tmdbId or tvdbId (required): External ID
            - title (required): Media title
            - year (optional): Release year
            - instanceName (required): Target ARR instance name
            - qualityProfileId (required): Quality profile to use
            - rootFolderPath (required): Root folder for downloads
            - monitored (optional, default true): Whether to monitor
            - searchOnAdd (optional, default true): Search immediately after adding

    Returns:
        Structured result with added/existing/invalid/failed lists
    """
    logger.debug("Serving POST /api/media/import")

    try:
        body = await request.json()
    except Exception:
        return error("Invalid request body", code="INVALID_BODY", status_code=400)

    items = body.get("items", [])
    if not items:
        return error("No items provided", code="NO_ITEMS", status_code=400)

    added = []
    existing = []
    invalid = []
    failed = []

    config = load_config()

    for item in items:
        tmdb_id = item.get("tmdbId")
        tvdb_id = item.get("tvdbId")
        title = item.get("title", "")
        instance_name = item.get("instanceName")
        quality_profile_id = item.get("qualityProfileId")
        root_folder = item.get("rootFolderPath")
        monitored = item.get("monitored", True)
        search_on_add = item.get("searchOnAdd", True)

        if not instance_name or not quality_profile_id or not root_folder:
            invalid.append({
                "title": title,
                "reason": "Missing required fields: instanceName, qualityProfileId, rootFolderPath",
            })
            continue

        if not tmdb_id and not tvdb_id:
            invalid.append({"title": title, "reason": "Either tmdbId or tvdbId is required"})
            continue

        # Determine instance type and get client
        instance_detail = None
        is_radarr = False
        if hasattr(config.instances, "radarr") and instance_name in config.instances.radarr:
            instance_detail = config.instances.radarr[instance_name]
            is_radarr = True
        elif hasattr(config.instances, "sonarr") and instance_name in config.instances.sonarr:
            instance_detail = config.instances.sonarr[instance_name]

        if not instance_detail or not instance_detail.url or not instance_detail.api:
            invalid.append({"title": title, "reason": f"Instance '{instance_name}' not found"})
            continue

        try:
            arr_client = create_arr_client(
                url=instance_detail.url,
                api=instance_detail.api,
                logger=logger,
            )
            if not arr_client:
                failed.append({"title": title, "reason": "Failed to create ARR client"})
                continue

            if is_radarr:
                # Check if movie already exists
                lookup_url = f"{arr_client.url}/api/v3/movie?tmdbId={tmdb_id}"
                existing_movies = arr_client.make_get_request(lookup_url) or []
                if existing_movies:
                    existing.append({"tmdbId": tmdb_id, "title": title, "instance": instance_name})
                    continue

                # Add movie
                movie_payload = {
                    "title": title,
                    "tmdbId": tmdb_id,
                    "year": item.get("year", 0),
                    "qualityProfileId": quality_profile_id,
                    "rootFolderPath": root_folder,
                    "monitored": monitored,
                    "minimumAvailability": "announced",
                    "addOptions": {"searchForMovie": search_on_add},
                }
                movie_url = f"{arr_client.url}/api/v3/movie"
                result = arr_client.make_post_request(movie_url, movie_payload)
                arr_id = result.get("id") if isinstance(result, dict) else None
                added.append({"tmdbId": tmdb_id, "title": title, "instance": instance_name, "arrId": arr_id})
            else:
                # Check if series already exists
                lookup_url = f"{arr_client.url}/api/v3/series?tvdbId={tvdb_id}"
                existing_series = arr_client.make_get_request(lookup_url) or []
                if existing_series:
                    existing.append({"tvdbId": tvdb_id, "title": title, "instance": instance_name})
                    continue

                # Add series
                series_payload = {
                    "title": title,
                    "tvdbId": tvdb_id,
                    "qualityProfileId": quality_profile_id,
                    "rootFolderPath": root_folder,
                    "monitored": monitored,
                    "addOptions": {
                        "searchForMissingEpisodes": search_on_add,
                        "ignoreEpisodesWithFiles": True,
                    },
                }
                series_url = f"{arr_client.url}/api/v3/series"
                result = arr_client.make_post_request(series_url, series_payload)
                arr_id = result.get("id") if isinstance(result, dict) else None
                added.append({"tvdbId": tvdb_id, "title": title, "instance": instance_name, "arrId": arr_id})

        except Exception as e:
            logger.error(f"Failed to import '{title}' to {instance_name}: {e}")
            failed.append({"title": title, "reason": str(e)})

    total = len(added) + len(existing)
    parts = []
    if added:
        parts.append(f"{len(added)} added")
    if existing:
        parts.append(f"{len(existing)} existing")
    if invalid:
        parts.append(f"{len(invalid)} invalid")
    if failed:
        parts.append(f"{len(failed)} failed")

    return ok(
        f"Imported {total} items: {', '.join(parts) or 'none'}",
        {"added": added, "existing": existing, "invalid": invalid, "failed": failed},
    )


@router.delete(
    "/collections/{collection_id}",
    summary="Delete a collection",
    description="Delete a specific collection cache item by its ID.",
    responses={
        200: {
            "description": "Collection deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Collection 5 deleted",
                        "data": {"deleted_id": 5},
                    }
                }
            },
        },
        404: {"description": "Collection not found"},
    },
)
async def delete_collection(
    collection_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Delete a collection cache item by ID.

    Permanently removes the specified collection from the database.
    This operation cannot be undone.

    Args:
        collection_id: The unique identifier of the collection to delete

    Returns:
        Confirmation of deletion with the deleted item ID
    """
    try:
        logger.debug(f"Serving DELETE /api/media/collections/{collection_id}")

        if not db.collection.get_by_id(collection_id):
            return error(
                "Collection not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        db.collection.delete_by_id(collection_id)

        return ok(f"Collection {collection_id} deleted", {"deleted_id": collection_id})

    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        return error(
            f"Error deleting collection: {str(e)}",
            code="COLLECTION_DELETE_ERROR",
            status_code=500,
        )


@router.post(
    "/collections",
    summary="Create collection",
    description="Create or upsert a media collection into the collections cache.",
    responses={
        200: {
            "description": "Collection created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Collection created successfully",
                        "data": {"collection": {"id": 1, "title": "My Collection"}},
                    }
                }
            },
        }
    },
)
async def create_collection(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Create a media collection.

    Parses request body for collection fields and upserts into the
    collections_cache table.

    Returns:
        Created or updated collection record
    """
    try:
        payload = await request.json()
        logger.debug(f"Serving POST /api/media/collections with payload: {payload}")

        title = payload.get("title")
        if not title:
            return error("Field 'title' is required", code="MISSING_TITLE", status_code=400)

        instance_name = payload.get("instance_name")
        if not instance_name:
            return error("Field 'instance_name' is required", code="MISSING_INSTANCE", status_code=400)

        record = {
            "title": title,
            "normalized_title": title.lower().strip() if title else None,
            "year": payload.get("year"),
            "tmdb_id": payload.get("tmdb_id"),
            "tvdb_id": payload.get("tvdb_id"),
            "imdb_id": payload.get("imdb_id"),
            "folder": payload.get("folder"),
            "library_name": payload.get("library_name"),
            "alternate_titles": payload.get("alternate_titles", []),
            "normalized_alternate_titles": payload.get("normalized_alternate_titles", []),
        }

        db.collection.upsert(record, instance_name)

        # Fetch the created/updated record
        created = db.collection.execute_query(
            "SELECT * FROM collections_cache WHERE title=? AND instance_name=?",
            (title, instance_name),
            fetch_one=True,
        )

        return ok("Collection created successfully", {"collection": created})

    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        return error(
            f"Error creating collection: {str(e)}",
            code="COLLECTION_CREATE_ERROR",
            status_code=500,
        )


@router.put(
    "/collections/{collection_id}",
    summary="Update collection",
    description="Update a media collection by merging provided fields.",
    responses={
        200: {
            "description": "Collection updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Collection updated successfully",
                        "data": {"collection": {"id": 1, "title": "Updated Collection"}},
                    }
                }
            },
        }
    },
)
async def update_collection(
    collection_id: int,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Update a media collection by ID.

    Fetches the existing collection, merges in the provided updates,
    and upserts the result back to the database.

    Args:
        collection_id: The unique identifier of the collection to update

    Returns:
        Updated collection record
    """
    try:
        payload = await request.json()
        logger.debug(f"Serving PUT /api/media/collections/{collection_id} with payload: {payload}")

        existing = db.collection.get_by_id(collection_id)
        if not existing:
            return error(
                f"Collection {collection_id} not found",
                code="COLLECTION_NOT_FOUND",
                status_code=404,
            )

        # Merge updates into existing record
        updatable_fields = [
            "title", "year", "tmdb_id", "tvdb_id", "imdb_id",
            "folder", "library_name", "alternate_titles",
            "normalized_alternate_titles",
        ]
        for field in updatable_fields:
            if field in payload:
                existing[field] = payload[field]

        # Update normalized_title if title changed
        if "title" in payload:
            existing["normalized_title"] = payload["title"].lower().strip() if payload["title"] else None

        instance_name = existing.get("instance_name")
        db.collection.upsert(existing, instance_name)

        # Fetch the updated record
        updated = db.collection.get_by_id(collection_id)

        return ok("Collection updated successfully", {"collection": updated})

    except Exception as e:
        logger.error(f"Error updating collection: {e}")
        return error(
            f"Error updating collection: {str(e)}",
            code="COLLECTION_UPDATE_ERROR",
            status_code=500,
        )


@router.post(
    "/duplicates/{group_id}/resolve",
    summary="Resolve duplicates",
    description="Resolve a group of duplicate media items by keeping one and removing the rest.",
    responses={
        200: {
            "description": "Resolution result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Resolved duplicate group: kept 1, removed 2",
                        "data": {
                            "kept": {"id": 1, "title": "Movie Title"},
                            "removed": [2, 3],
                            "failed": [],
                        },
                    }
                }
            },
        }
    },
)
async def resolve_duplicates(
    group_id: str,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Resolve duplicate media items within a group.

    Keeps the specified item and removes the others from both the
    ARR instance (with optional file deletion) and the local cache.

    Request body (JSON):
        keepId: ID of the media item to keep
        removeIds: List of media item IDs to remove
        deleteFiles: Whether to also delete files from disk (default false)
        addImportExclusion: Whether to add removed items to import exclusion list (default false)

    Args:
        group_id: Identifier for the duplicate group to resolve

    Returns:
        Resolution result with kept/removed/failed details
    """
    logger.debug(f"Serving POST /api/media/duplicates/{group_id}/resolve")

    try:
        body = await request.json()
    except Exception:
        return error("Invalid request body", code="INVALID_BODY", status_code=400)

    keep_id = body.get("keepId")
    remove_ids = body.get("removeIds", [])
    delete_files = body.get("deleteFiles", False)
    add_exclusion = body.get("addImportExclusion", False)

    if not keep_id:
        return error("keepId is required", code="MISSING_KEEP_ID", status_code=400)
    if not remove_ids:
        return error("removeIds is required", code="MISSING_REMOVE_IDS", status_code=400)

    # Verify the kept item exists
    kept_item = db.media.get_by_id(keep_id)
    if not kept_item:
        return error(
            f"Item to keep (id={keep_id}) not found",
            code="KEEP_ITEM_NOT_FOUND",
            status_code=404,
        )

    removed = []
    failed = []

    for rid in remove_ids:
        item = db.media.get_by_id(rid)
        if not item:
            failed.append({"id": rid, "reason": "not found in cache"})
            continue

        # Delete from ARR instance if possible
        if item.get("arr_id") and item.get("instance_name"):
            try:
                config = load_config()
                instance_name = item["instance_name"]
                arr_id = item["arr_id"]

                instance_detail = None
                if (
                    hasattr(config.instances, "radarr")
                    and instance_name in config.instances.radarr
                ):
                    instance_detail = config.instances.radarr[instance_name]
                elif (
                    hasattr(config.instances, "sonarr")
                    and instance_name in config.instances.sonarr
                ):
                    instance_detail = config.instances.sonarr[instance_name]

                if instance_detail and instance_detail.url and instance_detail.api:
                    arr_client = create_arr_client(
                        url=instance_detail.url,
                        api=instance_detail.api,
                        logger=logger,
                    )
                    if arr_client:
                        asset_type = item.get("asset_type", "movie")
                        endpoint_type = "movie" if asset_type == "movie" else "series"
                        params = f"deleteFiles={'true' if delete_files else 'false'}"
                        if add_exclusion:
                            params += "&addImportExclusion=true"
                        endpoint = f"{arr_client.url}/api/v3/{endpoint_type}/{arr_id}?{params}"
                        arr_client.make_delete_request(endpoint)
                        logger.info(
                            f"Deleted ARR media {arr_id} from {instance_name} "
                            f"(deleteFiles={delete_files}, exclusion={add_exclusion})"
                        )
                else:
                    logger.warning(
                        f"Instance {instance_name} not found in config, skipping ARR delete"
                    )
            except Exception as e:
                logger.error(f"ARR delete failed for id={rid}: {e}")
                # Continue with cache deletion even if ARR delete fails

        # Remove from local cache
        try:
            db.media.delete_by_id(rid)
            removed.append(rid)
        except Exception as e:
            failed.append({"id": rid, "reason": str(e)})

    msg = f"Resolved duplicate group: kept 1, removed {len(removed)}"
    if failed:
        msg += f", {len(failed)} failed"

    return ok(msg, {
        "kept": {"id": keep_id, "title": kept_item.get("title", "")},
        "removed": removed,
        "failed": failed,
    })


@router.post(
    "/fix-metadata",
    summary="Bulk fix metadata for all instances",
    description="Enqueue a cache refresh job for every configured instance "
    "to re-fetch and repair metadata across the entire library.",
    responses={
        200: {
            "description": "Bulk metadata fix jobs enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Bulk metadata fix initiated for 3 instances",
                        "data": {
                            "job_ids": [10, 11, 12],
                            "instances": ["radarr", "radarr4k", "sonarr"],
                        },
                    }
                }
            },
        }
    },
)
async def bulk_fix_metadata(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Bulk fix metadata for all configured instances.

    Enqueues a separate cache_refresh job (with update_mappings enabled)
    for every unique instance found in the media cache.

    Returns:
        List of enqueued job IDs and their corresponding instance names
    """
    try:
        logger.debug("Serving POST /api/media/fix-metadata")

        all_media = db.media.get_all()
        instances = list(
            {item["instance_name"] for item in all_media if item.get("instance_name")}
        )

        if not instances:
            return ok(
                "No instances found in media cache", {"job_ids": [], "instances": []}
            )

        job_ids = []
        for inst in instances:
            job_payload = {
                "arr_instances": [inst],
                "update_mappings": True,
            }
            result = db.worker.enqueue_job(
                "jobs", job_payload, job_type="cache_refresh"
            )
            if result.get("success"):
                job_ids.append(result.get("data", {}).get("job_id"))

        logger.info(f"Bulk metadata fix queued for {len(instances)} instances")

        return ok(
            f"Bulk metadata fix initiated for {len(instances)} instances",
            {"job_ids": job_ids, "instances": instances},
        )

    except Exception as e:
        logger.error(f"Error initiating bulk metadata fix: {e}")
        return error(
            f"Error initiating bulk metadata fix: {str(e)}",
            code="BULK_FIX_METADATA_ERROR",
            status_code=500,
        )


# --- Parameterized path endpoints (must be after static paths) ---


@router.get(
    "/{media_id}",
    summary="Get media item",
    description="Retrieve a single media item by its unique cache ID.",
    responses={
        200: {
            "description": "Media item retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media item retrieved",
                        "data": {
                            "id": 1,
                            "title": "The Matrix",
                            "year": 1999,
                            "imdb_id": "tt0133093",
                            "instance_name": "radarr",
                        },
                    }
                }
            },
        },
        404: {"description": "Media item not found"},
    },
)
async def get_media_item(
    media_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get a single media item by ID.

    Looks up the media cache entry by its unique integer ID and
    returns the full record including all metadata fields.

    Args:
        media_id: The unique identifier of the media item

    Returns:
        Complete media item record
    """
    try:
        logger.debug(f"Serving GET /api/media/{media_id}")

        item = db.media.get_by_id(media_id)
        if not item:
            return error(
                "Media item not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        return ok("Media item retrieved", item)

    except Exception as e:
        logger.error(f"Error retrieving media item {media_id}: {e}")
        return error(
            f"Error retrieving media item: {str(e)}",
            code="MEDIA_GET_ERROR",
            status_code=500,
        )


@router.put(
    "/{media_id}/metadata",
    summary="Update media metadata",
    description="Update one or more metadata fields for a specific media item.",
    responses={
        200: {
            "description": "Media item metadata updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media item 1 updated",
                        "data": {"updated_fields": ["rating", "studio"]},
                    }
                }
            },
        },
        400: {"description": "No valid fields provided"},
        404: {"description": "Media item not found"},
    },
)
async def update_media_metadata(
    media_id: int,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Update metadata fields for a media item.

    Accepts a JSON body with one or more updatable fields. Only
    whitelisted fields are applied; unknown keys are silently ignored.

    Args:
        media_id: The unique identifier of the media item to update

    Returns:
        List of field names that were updated
    """
    try:
        payload = await request.json()
        logger.debug(f"Serving PUT /api/media/{media_id}/metadata")

        item = db.media.get_by_id(media_id)
        if not item:
            return error(
                "Media item not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        updatable = {
            "matched_value",
            "original_file",
            "renamed_file",
            "file_hash",
            "poster_url",
            "arr_id",
            "status",
            "rating",
            "studio",
            "edition",
            "runtime",
            "language",
            "monitored",
        }
        update_kwargs = {k: v for k, v in payload.items() if k in updatable}

        if not update_kwargs:
            return error(
                "No valid fields to update",
                code="NO_FIELDS",
                status_code=400,
            )

        db.media.update(
            asset_type=item["asset_type"],
            title=item["title"],
            year=item["year"],
            instance_name=item["instance_name"],
            season_number=item.get("season_number"),
            **update_kwargs,
        )

        # Audit trail: capture each field's old→new so reverts and diffs
        # are possible later without having to replay the whole edit stream.
        from datetime import datetime as _dt

        edited_by = getattr(request.state, "user", "") or "unknown"
        now_iso = _dt.utcnow().isoformat()
        for field, new_value in update_kwargs.items():
            old_value = item.get(field)
            if old_value == new_value:
                continue
            try:
                db.worker.execute_query(
                    "INSERT INTO media_edit_history "
                    "(media_id, edited_at, edited_by, field, old_value, new_value) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        media_id,
                        now_iso,
                        edited_by,
                        field,
                        None if old_value is None else str(old_value),
                        None if new_value is None else str(new_value),
                    ),
                )
            except Exception as audit_err:
                logger.debug(f"Audit insert failed ({field}): {audit_err}")

        return ok(
            f"Media item {media_id} updated",
            {"updated_fields": list(update_kwargs.keys())},
        )

    except Exception as e:
        logger.error(f"Error updating media item {media_id}: {e}")
        return error(
            f"Error updating media item: {str(e)}",
            code="MEDIA_UPDATE_ERROR",
            status_code=500,
        )


@router.delete(
    "/{media_id}",
    summary="Delete media item",
    description="Delete a media item from the cache. Optionally delete "
    "the underlying files from the ARR instance.",
    responses={
        200: {
            "description": "Media item deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Media item 1 deleted",
                        "data": {"deleted_id": 1, "files_deleted": False},
                    }
                }
            },
        },
        404: {"description": "Media item not found"},
    },
)
async def delete_media_item(
    media_id: int,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Delete a media item from the cache.

    Accepts an optional JSON body with a ``deleteFiles`` flag. When
    true, the item is first removed from its ARR instance (with file
    deletion) before being purged from the local cache.

    Args:
        media_id: The unique identifier of the media item to delete

    Returns:
        Confirmation of deletion with file-deletion status
    """
    try:
        logger.debug(f"Serving DELETE /api/media/{media_id}")

        item = db.media.get_by_id(media_id)
        if not item:
            return error(
                "Media item not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        # Parse optional JSON body for deleteFiles flag
        delete_files = False
        try:
            if request.headers.get("content-type") == "application/json":
                body = await request.json()
                delete_files = body.get("deleteFiles", False)
        except Exception:
            pass

        # If deleteFiles requested, remove from ARR instance first
        if delete_files and item.get("arr_id") and item.get("instance_name"):
            try:
                config = load_config()
                instance_name = item["instance_name"]
                arr_id = item["arr_id"]

                # Look up instance URL/API from config (check radarr, sonarr, lidarr)
                instance_detail = None
                for arr_type in ("radarr", "sonarr", "lidarr"):
                    if (
                        hasattr(config.instances, arr_type)
                        and instance_name in getattr(config.instances, arr_type, {})
                    ):
                        instance_detail = getattr(config.instances, arr_type)[instance_name]
                        break

                if instance_detail and instance_detail.url and instance_detail.api:
                    arr_client = create_arr_client(
                        url=instance_detail.url,
                        api=instance_detail.api,
                        logger=logger,
                    )
                    if arr_client:
                        # Use deleteFiles query param on the ARR delete endpoint
                        endpoint = f"{arr_client.url}/api/v3/{'movie' if item.get('asset_type') == 'movie' else 'series'}/{arr_id}?deleteFiles=true"
                        arr_client.make_delete_request(endpoint)
                        logger.info(
                            f"Deleted ARR media {arr_id} with files from {instance_name}"
                        )
                else:
                    logger.warning(
                        f"Instance {instance_name} not found in config, skipping ARR delete"
                    )
            except Exception as arr_err:
                logger.error(f"ARR delete failed for {media_id}: {arr_err}")
                # Continue with cache deletion even if ARR delete fails

        db.media.delete_by_id(media_id)

        return ok(
            f"Media item {media_id} deleted",
            {"deleted_id": media_id, "files_deleted": delete_files},
        )

    except Exception as e:
        logger.error(f"Error deleting media item {media_id}: {e}")
        return error(
            f"Error deleting media item: {str(e)}",
            code="MEDIA_DELETE_ERROR",
            status_code=500,
        )


@router.post(
    "/{media_id}/fix-metadata",
    summary="Fix media metadata",
    description="Re-fetch metadata for a single media item by triggering "
    "a targeted cache refresh against its instance.",
    responses={
        200: {
            "description": "Metadata fix job enqueued successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Metadata fix initiated",
                        "data": {"job_id": 789, "instance": "radarr"},
                    }
                }
            },
        },
        404: {"description": "Media item not found"},
    },
)
async def fix_metadata(
    media_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Re-fetch metadata for a media item.

    Looks up the item's instance and enqueues a cache_refresh job
    targeting that instance with mapping updates enabled.

    Args:
        media_id: The unique identifier of the media item to fix

    Returns:
        Job ID and instance name for the enqueued refresh
    """
    try:
        logger.debug(f"Serving POST /api/media/{media_id}/fix-metadata")

        item = db.media.get_by_id(media_id)
        if not item:
            return error(
                "Media item not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        job_payload = {
            "arr_instances": [item["instance_name"]],
            "update_mappings": True,
        }
        result = db.worker.enqueue_job("jobs", job_payload, job_type="cache_refresh")

        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok(
                "Metadata fix initiated",
                {"job_id": job_id, "instance": item["instance_name"]},
            )

        return error(
            "Error enqueuing metadata fix",
            code="FIX_METADATA_ERROR",
            status_code=500,
        )

    except Exception as e:
        logger.error(f"Error fixing metadata for {media_id}: {e}")
        return error(
            f"Error fixing metadata: {str(e)}",
            code="FIX_METADATA_ERROR",
            status_code=500,
        )


# --- Capability endpoints: filters, exclusions, audit, smart collections ---


@router.get(
    "/low-rated",
    summary="List media below a rating threshold",
    description="Return media items whose `rating` text parses as a number "
    "below `max_rating` (default 5.0). Non-numeric ratings are excluded.",
)
async def get_low_rated(
    max_rating: float = 5.0,
    limit: int = 100,
    offset: int = 0,
    asset_type: Optional[str] = None,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        clauses = ["rating IS NOT NULL", "rating != ''", "CAST(rating AS REAL) < ?"]
        params: list = [float(max_rating)]
        if asset_type:
            clauses.append("asset_type=?")
            params.append(asset_type)
        where = "WHERE " + " AND ".join(clauses)
        rows = db.worker.execute_query(
            f"SELECT * FROM media_cache {where} "
            "ORDER BY CAST(rating AS REAL) ASC LIMIT ? OFFSET ?",
            tuple(params) + (limit, offset),
            fetch_all=True,
        ) or []
        return ok(
            f"Found {len(rows)} low-rated items",
            {"items": [dict(r) for r in rows], "limit": limit, "offset": offset},
        )
    except Exception as e:
        logger.error(f"Error querying low-rated media: {e}")
        return error(
            f"Error querying low-rated media: {str(e)}",
            code="LOW_RATED_ERROR",
            status_code=500,
        )


@router.get(
    "/incomplete-metadata",
    summary="List media with missing key metadata",
    description="Return media with NULL or empty values in any of the "
    "configurable set of key fields: rating, studio, language, genre.",
)
async def get_incomplete_metadata(
    fields: str = "rating,studio,language,genre",
    limit: int = 200,
    offset: int = 0,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        allowed = {
            "rating", "studio", "language", "genre", "runtime", "edition",
            "tmdb_id", "tvdb_id", "imdb_id", "year",
        }
        requested = [f.strip() for f in fields.split(",") if f.strip() in allowed]
        if not requested:
            return error(
                "No valid fields requested",
                code="INVALID_FIELDS",
                status_code=400,
            )
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        # INTEGER columns can't be empty-string; compare to NULL/0 instead.
        int_cols = {"tmdb_id", "tvdb_id", "runtime"}
        clauses = []
        for f in requested:
            if f in int_cols:
                clauses.append(f"({f} IS NULL OR {f} = 0)")
            else:
                clauses.append(f"({f} IS NULL OR {f} = '')")
        clause = " OR ".join(clauses)
        rows = db.worker.execute_query(
            f"SELECT * FROM media_cache WHERE {clause} "
            "ORDER BY title ASC LIMIT ? OFFSET ?",
            (limit, offset),
            fetch_all=True,
        ) or []
        return ok(
            f"Found {len(rows)} media items with incomplete metadata",
            {
                "items": [dict(r) for r in rows],
                "fields_checked": requested,
                "limit": limit,
                "offset": offset,
            },
        )
    except Exception as e:
        logger.error(f"Error querying incomplete metadata: {e}")
        return error(
            f"Error querying incomplete metadata: {str(e)}",
            code="INCOMPLETE_META_ERROR",
            status_code=500,
        )


@router.post(
    "/collections/from-tag",
    summary="Generate poster_collection from a tag",
    description="Create a new poster_collection containing every poster_cache "
    "row whose matching media_cache entry has the given tag in its tags field. "
    "Name defaults to the tag name.",
)
async def generate_collection_from_tag(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        payload = await request.json()
        tag = (payload.get("tag") or "").strip()
        if not tag:
            return error("tag required", code="TAG_REQUIRED", status_code=400)
        name = (payload.get("name") or tag).strip()

        # media_cache.tags is stored as serialized JSON in most paths, so we
        # match with LIKE on the raw string — good enough for a low-cardinality
        # tag list, and avoids requiring JSON1 extension support.
        media_rows = db.worker.execute_query(
            "SELECT id, tmdb_id, tvdb_id, imdb_id, season_number, title, year "
            "FROM media_cache WHERE tags LIKE ?",
            (f"%{tag}%",),
            fetch_all=True,
        ) or []
        if not media_rows:
            return ok(
                f"No media tagged '{tag}'",
                {"created": False, "matched_media": 0},
            )

        # Match each media row to a poster_cache row by identifiers.
        poster_ids: set = set()
        for m in media_rows:
            for id_field in ("tmdb_id", "tvdb_id", "imdb_id"):
                val = m[id_field]
                if not val:
                    continue
                prow = db.poster.get_by_id(
                    id_field, val, season_number=m["season_number"]
                )
                if prow:
                    poster_ids.add(prow["id"])
                    break

        if not poster_ids:
            return ok(
                f"Tag '{tag}' matched {len(media_rows)} media but no posters",
                {"created": False, "matched_media": len(media_rows)},
            )

        from datetime import datetime as _dt
        created_at = _dt.utcnow().isoformat()
        db.worker.execute_query(
            "INSERT INTO poster_collections (name, description, created_at) VALUES (?, ?, ?)",
            (name, f"Auto-generated from tag '{tag}'", created_at),
        )
        # Fetch new collection id
        row = db.worker.execute_query(
            "SELECT id FROM poster_collections WHERE name=? ORDER BY id DESC LIMIT 1",
            (name,),
            fetch_one=True,
        )
        coll_id = row["id"] if row else None
        if coll_id is None:
            return error(
                "Could not determine new collection id",
                code="COLLECTION_CREATE_ERROR",
                status_code=500,
            )

        for pid in poster_ids:
            try:
                db.worker.execute_query(
                    "INSERT OR IGNORE INTO poster_collection_items "
                    "(collection_id, poster_id) VALUES (?, ?)",
                    (coll_id, pid),
                )
            except Exception as ins_err:
                logger.debug(f"Skipping poster_id={pid}: {ins_err}")

        return ok(
            f"Created collection '{name}' with {len(poster_ids)} posters",
            {"collection_id": coll_id, "poster_count": len(poster_ids)},
        )
    except Exception as e:
        logger.error(f"Error generating collection from tag: {e}")
        return error(
            f"Error generating collection: {str(e)}",
            code="COLLECTION_FROM_TAG_ERROR",
            status_code=500,
        )


@router.get(
    "/{media_id}/history",
    summary="Media edit history",
    description="Return audit trail of metadata edits for a media item.",
)
async def get_media_history(
    media_id: int,
    limit: int = 100,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        rows = db.worker.execute_query(
            "SELECT * FROM media_edit_history WHERE media_id=? "
            "ORDER BY edited_at DESC LIMIT ?",
            (media_id, max(1, min(limit, 500))),
            fetch_all=True,
        ) or []
        return ok(
            f"Retrieved {len(rows)} history entries for media {media_id}",
            {"history": [dict(r) for r in rows]},
        )
    except Exception as e:
        logger.error(f"Error reading media history: {e}")
        return error(
            f"Error reading media history: {str(e)}",
            code="MEDIA_HISTORY_ERROR",
            status_code=500,
        )


@router.get(
    "/{media_id}/import-exclusion",
    summary="Check if media is excluded in its ARR",
    description="Query the media's ARR instance for its import-exclusion "
    "list and return whether this item's TMDB/TVDB ID is present.",
)
async def get_import_exclusion(
    media_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        item = db.media.get_by_id(media_id)
        if not item:
            return error("Media item not found", code="MEDIA_NOT_FOUND", status_code=404)
        instance_name = item.get("instance_name")
        cfg = load_config()
        inst_cfg = None
        service = None
        for svc in ("radarr", "sonarr", "lidarr"):
            pool = getattr(cfg.instances, svc, {})
            if instance_name in pool:
                inst_cfg = pool[instance_name]
                service = svc
                break
        if inst_cfg is None:
            return error(
                f"Instance {instance_name!r} not found",
                code="INSTANCE_NOT_FOUND",
                status_code=404,
            )
        client = create_arr_client(inst_cfg.url, inst_cfg.api, logger)
        if not (client and client.connect_status):
            return error(
                f"Could not connect to {instance_name}",
                code="INSTANCE_UNREACHABLE",
                status_code=502,
            )
        api_ver = "v1" if service == "lidarr" else "v3"
        exclusion_url = f"{inst_cfg.url.rstrip('/')}/api/{api_ver}/importlistexclusion"
        import requests as _rq
        resp = _rq.get(
            exclusion_url,
            headers={"X-Api-Key": inst_cfg.api},
            timeout=10,
        )
        if not resp.ok:
            return error(
                f"ARR responded {resp.status_code}",
                code="EXCLUSION_QUERY_ERROR",
                status_code=502,
            )
        entries = resp.json()
        tmdb = item.get("tmdb_id")
        tvdb = item.get("tvdb_id")
        excluded = any(
            (tmdb and e.get("tmdbId") == tmdb)
            or (tvdb and e.get("tvdbId") == tvdb)
            for e in entries or []
        )
        return ok(
            "Import exclusion status resolved",
            {
                "excluded": excluded,
                "service": service,
                "instance": instance_name,
                "exclusion_count": len(entries or []),
            },
        )
    except Exception as e:
        logger.error(f"Error resolving import exclusion: {e}")
        return error(
            f"Error resolving import exclusion: {str(e)}",
            code="EXCLUSION_ERROR",
            status_code=500,
        )


# --- Library Maintenance -------------------------------------------------


def _live_arr_ids_by_instance(config, logger) -> dict:
    """For each enabled ARR instance we can reach, return the set of live
    media ids. Unreachable instances are omitted so rows from them aren't
    mistakenly labelled orphaned."""
    live: dict[str, set] = {}
    for inst_type in ("radarr", "sonarr", "lidarr"):
        for name, info in getattr(config.instances, inst_type, {}).items():
            if not info.enabled:
                continue
            client = create_arr_client(info.url, info.api, logger)
            if not client or not client.connect_status:
                continue
            items = client.get_all_media() or []
            live[name] = {it.get("id") for it in items if it.get("id") is not None}
    return live


@router.get(
    "/orphaned",
    summary="List cache rows whose ARR entry no longer exists",
)
async def get_orphaned_cache(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        config = load_config()
        live = _live_arr_ids_by_instance(config, logger)
        rows = db.worker.execute_query(
            "SELECT id, title, asset_type, instance_name, arr_id, folder, root_folder "
            "FROM media_cache WHERE arr_id IS NOT NULL AND instance_name IS NOT NULL",
            fetch_all=True,
        ) or []
        orphaned = [
            dict(r) for r in rows
            if r["instance_name"] in live and r["arr_id"] not in live[r["instance_name"]]
        ]
        return ok(
            f"Found {len(orphaned)} orphaned cache row(s)",
            {
                "items": orphaned,
                "total": len(orphaned),
                "instances_checked": sorted(live.keys()),
            },
        )
    except Exception as e:
        logger.error(f"Error finding orphaned cache: {e}", exc_info=True)
        return error(
            f"Error finding orphaned cache: {str(e)}",
            code="ORPHANED_ERROR",
            status_code=500,
        )


class OrphanedPurgeRequest(BaseModel):
    ids: List[int]


@router.post(
    "/orphaned/purge",
    summary="Delete orphaned cache rows by id",
)
async def purge_orphaned_cache(
    body: OrphanedPurgeRequest,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        if not body.ids:
            return error(
                "No ids provided",
                code="NO_IDS",
                status_code=400,
            )
        placeholders = ",".join("?" for _ in body.ids)
        db.worker.execute_query(
            f"DELETE FROM media_cache WHERE id IN ({placeholders})",
            tuple(body.ids),
        )
        logger.info(f"Purged {len(body.ids)} orphaned cache row(s)")
        return ok(
            f"Purged {len(body.ids)} row(s) from cache",
            {"purged": len(body.ids)},
        )
    except Exception as e:
        logger.error(f"Error purging orphaned cache: {e}", exc_info=True)
        return error(
            f"Error purging orphaned cache: {str(e)}",
            code="PURGE_ERROR",
            status_code=500,
        )


class PathReplaceRequest(BaseModel):
    old_prefix: str
    new_prefix: str
    ids: Optional[List[int]] = None
    move_files: bool = False


def _scan_path_candidates(db: ChubDB, old_prefix: str, ids: Optional[List[int]]):
    if not old_prefix:
        return []
    base = (
        "SELECT id, title, asset_type, instance_name, arr_id, folder "
        "FROM media_cache WHERE folder IS NOT NULL AND folder LIKE ? "
        "AND arr_id IS NOT NULL AND instance_name IS NOT NULL"
    )
    params: list = [old_prefix + "%"]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        base += f" AND id IN ({placeholders})"
        params.extend(ids)
    rows = db.worker.execute_query(base, tuple(params), fetch_all=True) or []
    return [dict(r) for r in rows]


@router.post(
    "/paths/preview",
    summary="Preview a path prefix replace across all ARR instances",
)
async def preview_path_replace(
    body: PathReplaceRequest,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        if not body.old_prefix or not body.new_prefix:
            return error(
                "Both old_prefix and new_prefix are required",
                code="MISSING_PREFIX",
                status_code=400,
            )
        rows = _scan_path_candidates(db, body.old_prefix, body.ids)
        results = []
        for r in rows:
            new_path = body.new_prefix + r["folder"][len(body.old_prefix):]
            results.append({
                **r,
                "old_path": r["folder"],
                "new_path": new_path,
            })
        return ok(
            f"Preview: {len(results)} item(s) affected",
            {
                "items": results,
                "total": len(results),
                "old_prefix": body.old_prefix,
                "new_prefix": body.new_prefix,
            },
        )
    except Exception as e:
        logger.error(f"Error previewing path replace: {e}", exc_info=True)
        return error(
            f"Error previewing path replace: {str(e)}",
            code="PATH_PREVIEW_ERROR",
            status_code=500,
        )


@router.post(
    "/paths/apply",
    summary="Apply a path prefix replace across the selected ARR items",
)
async def apply_path_replace(
    body: PathReplaceRequest,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        if not body.old_prefix or not body.new_prefix:
            return error(
                "Both old_prefix and new_prefix are required",
                code="MISSING_PREFIX",
                status_code=400,
            )
        rows = _scan_path_candidates(db, body.old_prefix, body.ids)
        if not rows:
            return ok("No items match the prefix", {"applied": 0, "failed": 0, "results": []})

        config = load_config()

        def find_instance(name: str):
            for inst_type in ("radarr", "sonarr", "lidarr"):
                inst_map = getattr(config.instances, inst_type, {})
                if name in inst_map:
                    return inst_type, inst_map[name]
            return None, None

        resource_for_type = {"movie": "movie", "show": "series", "artist": "artist"}
        applied = 0
        failed = 0
        results = []
        move_flag = "true" if body.move_files else "false"

        for r in rows:
            new_path = body.new_prefix + r["folder"][len(body.old_prefix):]
            inst_type, inst_detail = find_instance(r["instance_name"])
            if not inst_detail or not inst_detail.url or not inst_detail.api:
                failed += 1
                results.append({**r, "new_path": new_path, "status": "instance_not_found"})
                continue
            client = create_arr_client(inst_detail.url, inst_detail.api, logger)
            if not client or not client.connect_status:
                failed += 1
                results.append({**r, "new_path": new_path, "status": "unreachable"})
                continue
            resource = resource_for_type.get(r["asset_type"])
            if not resource:
                failed += 1
                results.append({**r, "new_path": new_path, "status": "unsupported_type"})
                continue
            raw = client.make_get_request(f"{client.api_base}/{resource}/{r['arr_id']}")
            if not raw:
                failed += 1
                results.append({**r, "new_path": new_path, "status": "arr_fetch_failed"})
                continue
            raw["path"] = os.path.normpath(new_path)
            put_url = f"{client.api_base}/{resource}/{r['arr_id']}?moveFiles={move_flag}"
            resp = client.make_put_request(put_url, json=raw)
            if resp is None:
                failed += 1
                results.append({**r, "new_path": new_path, "status": "arr_put_failed"})
                continue
            applied += 1
            results.append({**r, "new_path": new_path, "status": "applied"})
            logger.info(
                f"Path update [{r['instance_name']}] {r['arr_id']}: {r['folder']} -> {new_path} "
                f"(move_files={body.move_files})"
            )

        return ok(
            f"Applied {applied} update(s), {failed} failure(s)",
            {"applied": applied, "failed": failed, "results": results},
        )
    except Exception as e:
        logger.error(f"Error applying path replace: {e}", exc_info=True)
        return error(
            f"Error applying path replace: {str(e)}",
            code="PATH_APPLY_ERROR",
            status_code=500,
        )
