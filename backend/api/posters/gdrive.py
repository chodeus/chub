"""Google Drive poster source sync endpoints."""

import os
from typing import Any, Dict, List

from fastapi import Depends, Query, Request
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
from backend.modules.sync_gdrive import SyncGDrive
from backend.util.config import ConfigError
from backend.util.database import ChubDB


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
            "Error retrieving GDrive statistics",
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
            "Error starting GDrive synchronization",
            code="GDRIVE_SYNC_START_ERROR",
            status_code=500,
        )


@router.post(
    "/gdrive/delete-local",
    summary="Delete a GDrive drive's local synced folder",
    description=(
        "Remove the on-disk folder a configured GDrive drive syncs into and "
        "purge its cached poster rows. Only deletes a folder that matches a "
        "currently-configured gdrive_list location; refuses anything else."
    ),
    responses={
        200: {"description": "Local folder removed and cache rows purged"},
        400: {"description": "Missing/invalid location or not a configured drive"},
        503: {"description": "Configuration unavailable"},
    },
)
async def delete_gdrive_local(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Delete the local synced folder for a removed GDrive drive and purge
    its poster_cache rows.

    Guardrails (defense in depth):
      - the location must be a non-empty string without null bytes and must
        not look like a CLI flag;
      - it must match (by realpath) the ``location`` of a currently
        configured ``gdrive_list`` entry — so only a real drive folder is
        ever deleted, never an arbitrary path. ``realpath`` collapses any
        ``..``/symlink games before the match, so traversal can't escape the
        configured set;
      - it must not resolve to the filesystem root.

    Membership is the authorization: a configured drive location is by
    definition an allowed root, so we don't also gate on ``is_path_allowed``
    — that check keys off roots that *exist on disk*, which would wrongly
    refuse (and skip the row purge for) a drive whose folder was already
    deleted manually. Purging works even when the folder is gone, so a
    partially cleaned-up drive still leaves no stale rows behind.
    """
    try:
        logger.debug("Serving POST /api/posters/gdrive/delete-local")

        body = await read_json_object(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        location = body.get("location")

        if (
            not location
            or not isinstance(location, str)
            or "\x00" in location
            or location.startswith("-")
        ):
            return error(
                "A valid 'location' is required",
                code="GDRIVE_LOCATION_REQUIRED",
                status_code=400,
            )

        from backend.util.config import load_config

        # Fail closed: without config we can't verify the path is a real drive.
        try:
            config = load_config()
        except ConfigError:
            raise
        except Exception:  # noqa: S110 — treated as unavailable below
            config = None
        if config is None:
            return error(
                "Configuration unavailable — cannot verify the drive folder",
                code="CONFIG_UNAVAILABLE",
                status_code=503,
            )

        # Must match a currently-configured gdrive_list location (by realpath),
        # so only an actual drive folder is ever deleted — never an arbitrary
        # path a caller invents.
        req_real = os.path.realpath(location)
        gdrive_list = getattr(config.sync_gdrive, "gdrive_list", None) or []
        matched = next(
            (
                e
                for e in gdrive_list
                if e.location and os.path.realpath(e.location) == req_real
            ),
            None,
        )
        if matched is None:
            return error(
                "Location is not a configured Google Drive folder",
                code="GDRIVE_LOCATION_NOT_CONFIGURED",
                status_code=400,
            )

        # Never delete the filesystem root, even if it were (pathologically)
        # configured as a drive location.
        if req_real == os.path.realpath(os.sep):
            return error(
                "Refusing to delete a filesystem root",
                code="GDRIVE_LOCATION_UNSAFE",
                status_code=400,
            )

        # Delete the folder (if still present) then purge cache rows. Rows are
        # indexed under the configured location string, so purge that; also
        # purge the realpath when it differs (symlinked mounts) so nothing is
        # left behind either way.
        import shutil

        # Delete the CONFIGURED folder (re-resolved), authorized by the membership
        # match above — never the raw request path, so a validated request string
        # can't reach rmtree. target == req_real by that match.
        target = os.path.realpath(matched.location)
        # Re-confine the RE-RESOLVED path right before deleting: a symlink
        # component can change between the membership check above and here.
        if target != req_real or target == os.path.realpath(os.sep):
            logger.error(f"Refusing to delete '{target}': resolved path changed")
            return error(
                "Location is not a configured Google Drive folder",
                code="GDRIVE_LOCATION_NOT_CONFIGURED",
                status_code=400,
            )

        folder_removed = False
        if os.path.isdir(target):
            shutil.rmtree(target)
            folder_removed = True

        deleted_rows = db.poster.delete_by_path_prefix(matched.location)
        if req_real != matched.location:
            deleted_rows += db.poster.delete_by_path_prefix(req_real)

        logger.info(
            f"Deleted local GDrive folder '{matched.name or matched.location}' "
            f"(removed={folder_removed}, {deleted_rows} cache rows purged)"
        )
        return ok(
            "Removed local drive folder and purged cached posters",
            {
                "folder_removed": folder_removed,
                "deleted_rows": deleted_rows,
                "location": matched.location,
            },
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error deleting local GDrive folder: {e}")
        return error(
            "Error deleting local GDrive folder",
            code="GDRIVE_DELETE_LOCAL_ERROR",
            status_code=500,
        )
