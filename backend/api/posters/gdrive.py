"""Google Drive poster source sync endpoints."""

import json
import os
from typing import Any, Dict, List, Optional, Set

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
    worker_error,
)
from backend.modules.sync_gdrive import SyncGDrive
from backend.util.config import ConfigError
from backend.util.database import ChubDB


def _in_flight(db: ChubDB, job_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The job a deduped enqueue collapsed onto, while it is still queued or running."""
    if not job_result.get("deduped"):
        return None
    job = db.worker.get_job_by_id("jobs", job_result.get("data", {}).get("job_id"))
    return job if job and job.get("status") in ("pending", "running") else None


def _covers(job: Dict[str, Any], requested: Set[str]) -> bool:
    """Whether a queued sync job will sync every requested folder."""
    # A running job may be past a folder already, or read the folder list before it changed.
    if job.get("status") != "pending" or not job.get("payload"):
        return False
    try:
        args = json.loads(job["payload"]).get("module_args") or {}
    except (AttributeError, ValueError):
        return False
    only = args.get("only_folders")
    # An empty list syncs every folder, as SyncGDrive.run reads it.
    return not only or requested <= set(only)


def _already_queued(
    job: Dict[str, Any], requested: Set[str], scope: str, data: Dict[str, Any]
) -> JSONResponse:
    """The reply when enqueue_job collapsed this request onto another sync job."""
    job_id = job.get("id")
    state = {"pending": "queued"}.get(job.get("status"), job.get("status"))
    if _covers(job, requested):
        return ok(
            f"A GDrive sync covering {scope} is already queued (job {job_id})",
            {**data, "deduped": True},
        )
    return error(
        f"A GDrive sync is already {state} (job {job_id}); "
        f"sync {scope} again once it finishes",
        code="GDRIVE_SYNC_BUSY",
        status_code=409,
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
def get_gdrive_stats(
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
    description="Queue one GDrive sync job for the selected folders.",
    responses={
        200: {
            "description": "GDrive sync job queued, or a queued one already covers these folders",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "GDrive sync queued for 2 folders: Movies, TV Shows",
                        "data": {"job_id": 123, "queued_count": 2, "scope": "subset"},
                    }
                }
            },
        },
        400: {"description": "No GDrive folder names provided"},
        409: {"description": "A GDrive sync is running, or queued without these folders"},
    },
)
def sync_gdrive_folders(
    gdrive_names: List[str] = Query(
        ..., description="Names of the GDrive folders to sync"
    ),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """Queue one sync job for the selected folders, or name the sync job already covering them."""
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
        other = _in_flight(db, job_result)
        if job_result.get("deduped") and other is None:
            # The job it collapsed onto finished before it could be read: queue once more.
            job_result = db.worker.enqueue_job(
                "jobs", payload=payload, job_type="module_run"
            )
            other = _in_flight(db, job_result)
        # A failed enqueue used to answer "started" with no job behind it.
        failed = worker_error(
            job_result,
            logger,
            "Error starting the GDrive sync",
            "GDRIVE_SYNC_ENQUEUE_ERROR",
        )
        if failed:
            return failed
        queued = job_result.get("data", {})
        job_id = queued.get("job_id")

        if is_full_set:
            scope = f"all {len(configured)} folders"
            data = {"job_id": job_id, "scope": "all"}
        elif is_single:
            only = next(iter(requested))
            scope = f"'{only}'"
            data = {"job_id": job_id, "name": only, "scope": "single"}
        else:
            scope = f"{len(requested)} folders: {', '.join(sorted(requested))}"
            data = {"job_id": job_id, "queued_count": len(requested), "scope": "subset"}
        if job_result.get("deduped"):
            seen = {"id": job_id, "status": queued.get("status")}
            return _already_queued(other or seen, requested, scope, data)
        return ok(f"GDrive sync queued for {scope}", data)

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
