"""
Labelarr tag synchronization API endpoints for CHUB.

Provides tag synchronization functionality between ARR services
(Radarr/Sonarr) and Plex for automated label management.
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.config import ChubConfig, load_config

router = APIRouter(
    prefix="/api",
    tags=["Labelarr"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Instance or resource not found"},
    },
)


class TagActions(BaseModel):
    """Tag actions schema for explicit add/remove operations."""

    add: List[str] = []
    remove: List[str] = []


class SyncTagsRequest(BaseModel):
    """Request schema for syncing tags from ARR to Plex."""

    source_instance: str
    media_cache_id: int
    plex_mapping_id: Optional[int] = None
    tag_actions: TagActions = TagActions()
    plex_instance: Optional[str] = None  # Let backend determine if not provided
    dry_run: bool = False


def get_config() -> ChubConfig:
    """Load and return the current configuration."""
    return load_config()


@router.post(
    "/labelarr/sync",
    summary="Sync tags to Plex",
    description="Synchronize tags from ARR services to Plex labels through background job processing.",
    responses={
        200: {
            "description": "Tag sync job created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Labelarr sync job created successfully",
                        "data": {
                            "job_id": 123,
                            "status": "queued",
                            "media_cache_id": 456,
                            "source_instance": "radarr-main",
                            "plex_instance": "plex-main",
                        },
                    }
                }
            },
        },
        404: {"description": "ARR or Plex instance not found in configuration"},
    },
)
async def sync_tags_to_plex(
    request_data: SyncTagsRequest,
    request: Request,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Synchronize tags from ARR instance to Plex labels.

    Creates a background job to handle the tag sync operation using the
    labelarr module. Tags can be explicitly added or removed, and the
    operation supports dry-run mode for testing.

    The sync process maps media between ARR services and Plex, then
    applies the specified tag operations to maintain label consistency.

    Args:
        request_data: Sync request with media IDs, tag operations, and instances
        request: FastAPI request object for database access
        config: Application configuration for instance validation
        logger: Logger instance for operation tracking

    Returns:
        Job ID and status for monitoring sync progress
    """
    try:
        logger.info(
            f"Creating labelarr sync job for media_cache_id {request_data.media_cache_id}"
        )

        # Determine Plex instance - use first available if not specified
        plex_instance = request_data.plex_instance
        if not plex_instance:
            if hasattr(config.instances, "plex") and config.instances.plex:
                plex_instance = list(config.instances.plex.keys())[0]
                logger.info(
                    f"No plex_instance specified, using first available: {plex_instance}"
                )
            else:
                return error(
                    "No Plex instances available",
                    code="NO_PLEX_INSTANCES",
                    status_code=404,
                )

        # Validate the determined Plex instance exists in config
        if (
            not hasattr(config.instances, "plex")
            or plex_instance not in config.instances.plex
        ):
            return error(
                f"Plex instance '{plex_instance}' not found",
                code="PLEX_INSTANCE_NOT_FOUND",
                status_code=404,
            )

        # Check if ARR instance exists (Radarr, Sonarr, or Lidarr)
        arr_found = False
        for arr_type in ("radarr", "sonarr", "lidarr"):
            if hasattr(
                config.instances, arr_type
            ) and request_data.source_instance in getattr(
                config.instances, arr_type, {}
            ):
                arr_found = True
                break

        if not arr_found:
            return error(
                f"ARR instance '{request_data.source_instance}' not found",
                code="ARR_INSTANCE_NOT_FOUND",
                status_code=404,
            )

        # Get database from app state
        db = get_database(request)
        if not db:
            return error(
                "Database not available",
                code="DATABASE_NOT_AVAILABLE",
                status_code=500,
            )

        # Single-item sync routes through the same labelarr_bulk_sync
        # path as multi-item, just with a one-element list and notify
        # disabled. UI toast is the user's feedback for a single-item
        # click; one Discord ping per click would be noise. The bulk
        # processor handles single-element lists identically.
        job_payload = {
            "source_instance": request_data.source_instance,
            "media_cache_ids": [request_data.media_cache_id],
            "tag_actions": request_data.tag_actions.model_dump(),
            "plex_instance": plex_instance,
            "dry_run": request_data.dry_run,
            "notify": False,
        }

        result = db.worker.enqueue_job(
            table_name="jobs", payload=job_payload, job_type="labelarr_bulk_sync"
        )

        if result["success"]:
            job_id = result["data"]["job_id"]
            logger.info(f"Labelarr sync job {job_id} queued successfully")

            return ok(
                "Labelarr sync job created successfully",
                {
                    "job_id": job_id,
                    "status": "queued",
                    "media_cache_id": request_data.media_cache_id,
                    "source_instance": request_data.source_instance,
                    "plex_instance": plex_instance,
                },
            )
        else:
            return error(
                f"Failed to create labelarr sync job: {result['message']}",
                code="JOB_CREATION_FAILED",
                status_code=500,
            )

    except Exception as e:
        logger.error(f"Error creating labelarr sync job: {e}", exc_info=True)
        return error(
            "Failed to create sync job",
            code="SYNC_JOB_ERROR",
            status_code=500,
        )


class BulkTagRequest(BaseModel):
    """Request schema for applying/removing a tag across many media items."""

    source_instance: str
    media_cache_ids: List[int]
    tag_actions: TagActions
    plex_instance: Optional[str] = None
    dry_run: bool = False


@router.post(
    "/labelarr/bulk-sync",
    summary="Bulk sync tags for many media items",
    description="Enqueue one labelarr_bulk_sync job covering every "
    "media_cache_id. Returns the job ID so the frontend can poll it. "
    "Mirrors /labelarr/sync payload but takes `media_cache_ids: [int]` "
    "and sends one aggregate Discord summary at the end.",
)
async def bulk_sync_tags(
    request_data: BulkTagRequest,
    request: Request,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    try:
        if not request_data.media_cache_ids:
            return error(
                "media_cache_ids is empty",
                code="NO_MEDIA_IDS",
                status_code=400,
            )
        if len(request_data.media_cache_ids) > 1000:
            return error(
                "Too many items in a single bulk request (max 1000)",
                code="BULK_TOO_LARGE",
                status_code=400,
            )

        # Validate ARR instance once instead of per-item.
        arr_found = False
        for arr_type in ("radarr", "sonarr", "lidarr"):
            if request_data.source_instance in getattr(config.instances, arr_type, {}):
                arr_found = True
                break
        if not arr_found:
            return error(
                f"ARR instance '{request_data.source_instance}' not found",
                code="ARR_INSTANCE_NOT_FOUND",
                status_code=404,
            )

        plex_instance = request_data.plex_instance
        if not plex_instance and config.instances.plex:
            plex_instance = list(config.instances.plex.keys())[0]
        if not plex_instance or plex_instance not in (config.instances.plex or {}):
            return error(
                "No valid Plex instance",
                code="PLEX_INSTANCE_NOT_FOUND",
                status_code=404,
            )

        db = get_database(request)
        if not db:
            return error(
                "Database not available",
                code="DATABASE_NOT_AVAILABLE",
                status_code=500,
            )

        # Enqueue ONE bulk job covering every requested media_cache_id
        # instead of N silent per-item jobs. The bulk processor sends a
        # single aggregate Discord/Notifiarr/Email summary at the end.
        # Per-item /labelarr/sync is unaffected and still routes through
        # the silent ad-hoc path (UI gives immediate toast feedback).
        payload = {
            "source_instance": request_data.source_instance,
            "media_cache_ids": request_data.media_cache_ids,
            "tag_actions": request_data.tag_actions.model_dump(),
            "plex_instance": plex_instance,
            "dry_run": request_data.dry_run,
        }
        result = db.worker.enqueue_job(
            table_name="jobs", payload=payload, job_type="labelarr_bulk_sync"
        )

        if not result.get("success"):
            return error(
                result.get("message", "Failed to enqueue bulk labelarr job"),
                code="JOB_ENQUEUE_FAILED",
                status_code=500,
            )

        job_id = result["data"]["job_id"]
        logger.info(
            f"Bulk labelarr: enqueued job {job_id} for {len(request_data.media_cache_ids)} items"
        )
        return ok(
            f"Enqueued bulk labelarr sync for {len(request_data.media_cache_ids)} items",
            {
                "job_id": job_id,
                "queued_count": len(request_data.media_cache_ids),
                "plex_instance": plex_instance,
                "source_instance": request_data.source_instance,
                "dry_run": request_data.dry_run,
            },
        )
    except Exception as e:
        logger.error(f"Error in bulk labelarr sync: {e}", exc_info=True)
        return error(
            "Bulk sync failed",
            code="BULK_SYNC_ERROR",
            status_code=500,
        )
