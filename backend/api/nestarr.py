# api/nestarr.py

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_module_logger, ok
from backend.modules.nestarr import Nestarr
from backend.util.arr import create_arr_client
from backend.util.config import load_config
from backend.util.database import ChubDB

SCAN_TYPE = "nestarr"


def _get_db_base(db: ChubDB):
    """Get a DatabaseBase interface from ChubDB for raw queries."""
    # ChubDB is a facade; use any sub-interface (e.g. media) for execute_query
    return db.media


def _save_scan_cache(db: ChubDB, issues: list, instances_checked: list, logger=None) -> None:
    """Persist scan results to the scan_cache table."""
    try:
        scanned_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(
            {
                "issues": issues,
                "total": len(issues),
                "instances_checked": instances_checked,
            },
            default=str,
        )
        _get_db_base(db).execute_query(
            "INSERT OR REPLACE INTO scan_cache (scan_type, data, scanned_at) VALUES (?, ?, ?)",
            (SCAN_TYPE, payload, scanned_at),
        )
        if logger:
            logger.debug(f"Saved {len(issues)} scan results to cache")
    except Exception as e:
        if logger:
            logger.error(f"Failed to save scan cache: {e}")


def _load_scan_cache(db: ChubDB, logger=None) -> dict | None:
    """Load cached scan results from the scan_cache table."""
    try:
        row = _get_db_base(db).execute_query(
            "SELECT data, scanned_at FROM scan_cache WHERE scan_type = ?",
            (SCAN_TYPE,),
            fetch_one=True,
        )
        if row and row.get("data"):
            result = json.loads(row["data"])
            result["scanned_at"] = row.get("scanned_at")
            if logger:
                logger.debug(
                    f"Loaded {result.get('total', 0)} cached scan results "
                    f"from {result.get('scanned_at', '?')}"
                )
            return result
    except Exception as e:
        if logger:
            logger.error(f"Failed to load scan cache: {e}")
    return None

router = APIRouter(
    prefix="/api/nestarr",
    tags=["nestarr"],
)


@router.get("/results")
async def get_cached_scan_results(request: Request, db: ChubDB = Depends(get_database)):
    """Return the most recent cached scan results, or empty if no scan has been run."""
    logger = get_module_logger(request, "nestarr")
    cached = _load_scan_cache(db, logger=logger)
    if cached:
        return ok(
            message="Cached scan results loaded",
            data=cached,
        )
    return ok(
        message="No cached scan results available",
        data={"issues": [], "total": 0, "instances_checked": [], "scanned_at": None},
    )


class FixRequest(BaseModel):
    instance_type: str  # "radarr", "sonarr", or "lidarr"
    instance_name: str
    media_id: int
    target_path: str


@router.get("/scan")
async def scan_nested_media(request: Request, db: ChubDB = Depends(get_database)):
    """
    Compare ARR media against Plex to find unmatched items,
    and scan for incorrectly nested media paths.
    Returns a list of issues with suggested actions.
    """
    logger = get_module_logger(request, "nestarr")

    try:
        config = load_config()
        library_mappings = (
            config.nestarr.library_mappings if config.nestarr.library_mappings else None
        )
        path_mapping = (
            config.nestarr.path_mapping if config.nestarr.path_mapping else None
        )
        issues = Nestarr.scan_instances(
            config.instances, logger, db=db,
            library_mappings=library_mappings,
            path_mapping=path_mapping,
        )

        instances_checked = set()
        for inst_type in ["radarr", "sonarr", "lidarr"]:
            instances = getattr(config.instances, inst_type, {})
            for name, info in instances.items():
                if info.enabled:
                    instances_checked.add(name)

        sorted_instances = sorted(instances_checked)
        _save_scan_cache(db, issues, sorted_instances, logger=logger)

        return ok(
            message=f"Scan complete. Found {len(issues)} nesting issue(s).",
            data={
                "issues": issues,
                "total": len(issues),
                "instances_checked": sorted_instances,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.error(f"Scan failed: {e}", exc_info=True)
        return error(
            message=f"Scan failed: {str(e)}",
            code="SCAN_FAILED",
            status_code=500,
        )


def _get_arr_client(config, body, logger):
    """Shared helper to validate input and return an ARR client."""
    if body.instance_type not in ("radarr", "sonarr", "lidarr"):
        return None, error(
            message="instance_type must be 'radarr', 'sonarr', or 'lidarr'",
            code="INVALID_INSTANCE_TYPE",
        )

    instances = getattr(config.instances, body.instance_type, {})
    instance_info = instances.get(body.instance_name)
    if not instance_info:
        return None, error(
            message=f"Instance '{body.instance_name}' not found in {body.instance_type} config",
            code="INSTANCE_NOT_FOUND",
            status_code=404,
        )

    app = create_arr_client(instance_info.url, instance_info.api, logger)
    if not app or not app.is_connected():
        return None, error(
            message=f"Cannot connect to {body.instance_name}",
            code="CONNECTION_FAILED",
            status_code=502,
        )

    return app, None


@router.post("/preview")
async def preview_fix(request: Request, body: FixRequest):
    """
    Preview what a fix would do — shows the current path, the target path,
    and any pending file/folder renames from the ARR naming format.
    No changes are made.
    """
    logger = get_module_logger(request, "nestarr")

    try:
        config = load_config()
        app, err_response = _get_arr_client(config, body, logger)
        if err_response:
            return err_response

        resource_map = {"radarr": "movie", "sonarr": "series", "lidarr": "artist"}
        resource = resource_map[body.instance_type]

        raw_media = app.make_get_request(
            f"{app.api_base}/{resource}/{body.media_id}"
        )
        if not raw_media:
            return error(
                message=f"Media item {body.media_id} not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        old_path = raw_media.get("path", "")
        new_path = os.path.normpath(body.target_path)

        # Get pending renames from the ARR rename preview API.
        # This shows what the files/folders WOULD be renamed to
        # based on the instance's naming format settings.
        rename_preview = []
        try:
            raw_renames = app.get_rename_list(body.media_id) or []
            for item in raw_renames:
                rename_preview.append({
                    "existing_path": item.get("existingPath", ""),
                    "new_path": item.get("newPath", ""),
                })
        except Exception:
            pass  # Rename preview is best-effort

        return ok(
            message="Preview generated — no changes made",
            data={
                "title": raw_media.get("title", "Unknown"),
                "year": raw_media.get("year"),
                "media_id": body.media_id,
                "instance": body.instance_name,
                "instance_type": body.instance_type,
                "current_path": old_path,
                "target_path": new_path,
                "rename_preview": rename_preview,
                "already_correct": os.path.normpath(old_path) == new_path,
            },
        )

    except Exception as e:
        logger.error(f"Preview failed: {e}", exc_info=True)
        return error(
            message=f"Preview failed: {str(e)}",
            code="PREVIEW_FAILED",
            status_code=500,
        )


@router.post("/fix")
async def fix_nested_media(request: Request, body: FixRequest):
    """
    Fix a nested media item by updating its path in Radarr/Sonarr and
    moving files to the correct location, then triggering a rename
    to match the instance's naming format.
    """
    logger = get_module_logger(request, "nestarr")

    try:
        config = load_config()
        app, err_response = _get_arr_client(config, body, logger)
        if err_response:
            return err_response

        resource_map = {"radarr": "movie", "sonarr": "series", "lidarr": "artist"}
        resource = resource_map[body.instance_type]

        # 1. GET the raw media object from the ARR API
        raw_media = app.make_get_request(
            f"{app.api_base}/{resource}/{body.media_id}"
        )
        if not raw_media:
            return error(
                message=f"Media item {body.media_id} not found",
                code="MEDIA_NOT_FOUND",
                status_code=404,
            )

        old_path = raw_media.get("path", "")
        new_path = os.path.normpath(body.target_path)

        if os.path.normpath(old_path) == new_path:
            return ok(
                message="Media is already at the target path — no move needed",
                data={"media_id": body.media_id, "path": new_path},
            )

        # Respect dry_run config — preview only, no actual changes
        if getattr(config.nestarr, "dry_run", False):
            logger.info(
                f"[DRY RUN] Would move {body.instance_type} item {body.media_id}: "
                f"{old_path} -> {new_path}"
            )
            return ok(
                message=f"[Dry Run] Would move media to {new_path} — no changes made",
                data={
                    "media_id": body.media_id,
                    "old_path": old_path,
                    "new_path": new_path,
                    "dry_run": True,
                },
            )

        # 2. Update the path field
        raw_media["path"] = new_path

        # 3. PUT it back with moveFiles=true to physically relocate
        result = app.make_put_request(
            f"{app.api_base}/{resource}/{body.media_id}?moveFiles=true",
            json=raw_media,
        )

        if result is None:
            return error(
                message="ARR API returned no response — the move may not have succeeded",
                code="MOVE_UNCERTAIN",
                status_code=502,
            )

        logger.info(
            f"Moved {body.instance_type} item {body.media_id}: "
            f"{old_path} -> {new_path}"
        )

        # 4. Trigger rename so the folder and file names match
        #    the instance's configured naming format.
        rename_triggered = False
        try:
            app.rename_media([body.media_id])
            rename_triggered = True
            logger.info(
                f"Triggered rename for {body.instance_type} item {body.media_id}"
            )
        except Exception as rename_err:
            logger.warning(
                f"Move succeeded but rename command failed: {rename_err}. "
                "The media is in the correct location but may need a manual rename."
            )

        return ok(
            message=f"Successfully moved media to {new_path}",
            data={
                "media_id": body.media_id,
                "old_path": old_path,
                "new_path": new_path,
                "rename_triggered": rename_triggered,
            },
        )

    except Exception as e:
        logger.error(f"Fix failed: {e}", exc_info=True)
        return error(
            message=f"Fix failed: {str(e)}",
            code="FIX_FAILED",
            status_code=500,
        )
