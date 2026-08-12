"""
System-level API endpoints for CHUB.

Provides core system functionality including version information,
directory operations, and testing utilities.
"""

import io
import json
import os
import shutil
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.backup import get_backup_dir, save_backup
from backend.util.config import (
    ConfigError,
    ChubConfig,
    get_config_path,
    load_config,
    save_config,
)
from backend.util.database import ChubDB
from backend.util.path_safety import get_browse_roots, is_path_allowed
from backend.util.version import check_for_update, get_version

router = APIRouter(
    prefix="/api",
    tags=["System"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Bad request"},
    },
)

# Caps for restore uploads. A real chub backup is config.yml (KBs) plus a SQL
# dump of chub.db (tens of MBs even for very large libraries), so these sit
# far above any legitimate backup while still bounding a hostile upload or
# zip bomb.
MAX_RESTORE_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_RESTORE_CONFIG_BYTES = 10 * 1024 * 1024
MAX_RESTORE_SQL_BYTES = 2 * 1024 * 1024 * 1024


class TestEndpointRequest(BaseModel):
    """Request model for the test endpoint."""

    message: str = "test"
    data: Any = None


class FolderCreationRequest(BaseModel):
    """Request model for folder creation."""

    path: str


@router.get(
    "/version",
    summary="Get application version",
    description="Returns the current CHUB application version information.",
    responses={
        200: {
            "description": "Version information retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Version retrieved",
                        "data": {"version": "3.0.0-alpha"},
                    }
                }
            },
        }
    },
)
async def get_version_endpoint(logger: Any = Depends(get_logger)) -> JSONResponse:
    """
    Get the current application version.

    Returns version information from the build system for display
    in the UI and for API client compatibility checks.
    """
    try:
        version = get_version()
        logger.debug(f"Serving GET /api/version: {version}")
        return ok("Version retrieved", {"version": version})
    except Exception as e:
        logger.error(f"Error getting version: {e}")
        return error(
            "Error getting version", code="VERSION_ERROR", status_code=500
        )


@router.get(
    "/version/check",
    summary="Check for updates",
    description="On-demand check of the remote release manifest for a newer build.",
)
async def check_version_endpoint(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Poll the remote manifest and report whether a newer build is available.

    The network calls are blocking, so they run off the event loop. Failures
    degrade gracefully to `checked: false` rather than erroring.
    """
    try:
        result = await run_in_threadpool(check_for_update, logger)
        return ok("Update check complete", result)
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return error(
            "Error checking for updates",
            code="VERSION_CHECK_ERROR",
            status_code=500,
        )


@router.get(
    "/health",
    summary="Application health check",
    description="Returns application health status for load balancers and Docker HEALTHCHECK.",
    responses={
        200: {
            "description": "Application is healthy",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Healthy",
                        "data": {
                            "status": "ok",
                            "version": "3.0.0-alpha",
                            "uptime_seconds": 3600,
                        },
                    }
                }
            },
        }
    },
)
async def health_check(request: Request) -> JSONResponse:
    """
    Application-level health check.

    Returns status, version, uptime, and basic worker/database health.
    Exempt from authentication so load balancers and Docker can probe it.
    """
    status = "ok"
    checks = {}

    # Uptime
    started_at = getattr(request.app.state, "started_at", None)
    uptime = round(time.time() - started_at, 1) if started_at else None

    # Worker health
    for name in ("webhook_worker", "background_worker"):
        worker = getattr(request.app.state, name, None)
        if worker:
            stats = (
                worker.get_worker_stats() if hasattr(worker, "get_worker_stats") else {}
            )
            checks[name] = stats.get("status", "unknown")
            if stats.get("status") != "running":
                status = "degraded"

    # Database health
    db = getattr(request.app.state, "db", None)
    if db:
        try:
            db.worker.execute_query("SELECT 1")
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
            status = "degraded"

    version = get_version()

    return ok(
        "Healthy" if status == "ok" else "Degraded",
        {
            "status": status,
            "version": version,
            "uptime_seconds": uptime,
            "checks": checks,
        },
    )


@router.get(
    "/system/disk",
    summary="Disk usage for configured mount points",
    description=(
        "Reports free/used/total bytes for the container mount points "
        "CHUB cares about (/config, /kometa, /media, /plex, /data). "
        "Used by the dashboard for at-a-glance health."
    ),
)
async def system_disk() -> JSONResponse:
    """Return disk usage for the standard CHUB mount points.

    Any mount that doesn't exist (i.e. not bind-mounted by the user) is
    reported with `exists: false` so the frontend can hide it silently.
    """
    targets = ["/config", "/kometa", "/media", "/plex", "/data"]
    out = []
    seen_devices: dict[int, list[str]] = {}
    for path in targets:
        entry: dict[str, Any] = {"path": path, "exists": os.path.isdir(path)}
        if entry["exists"]:
            try:
                st = os.stat(path)
                entry["device_id"] = st.st_dev
                usage = shutil.disk_usage(path)
                entry["total_bytes"] = usage.total
                entry["used_bytes"] = usage.used
                entry["free_bytes"] = usage.free
                entry["percent_used"] = round((usage.used / usage.total) * 100, 1)
                # Track colocated paths on the same underlying device so the
                # frontend can dedupe (Unraid bind-mounts often share /mnt/cache).
                seen_devices.setdefault(st.st_dev, []).append(path)
            except OSError as exc:
                entry["error"] = str(exc)
        out.append(entry)
    # Annotate each entry with its "siblings" on the same device.
    for entry in out:
        dev = entry.get("device_id")
        if dev is not None:
            siblings = [p for p in seen_devices.get(dev, []) if p != entry["path"]]
            entry["shared_with"] = siblings
    return ok("Disk usage snapshot", {"mounts": out})


@router.get(
    "/directory",
    summary="List directory contents",
    description="Lists directories within the specified path for configuration and file management.",
    responses={
        200: {
            "description": "Directory listing retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Listed 3 directories",
                        "data": {
                            "directories": ["Documents", "Downloads", "Pictures"],
                            "exists": True,
                            "writable": True,
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid path or path does not exist"},
    },
)
async def list_directory(
    path: str = "/", logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    List directories within a specified path.

    Used by the UI for path selection in configuration forms.
    Only returns directories, not files, and excludes hidden directories.
    Includes metadata about path existence and write permissions.

    Args:
        path: The directory path to list (defaults to root)

    Returns:
        Dictionary containing directories list and path metadata
    """
    try:
        # Restrict to configured allowed roots
        try:
            config = load_config()
        except ConfigError:
            config = None

        # Fail closed: if the config can't be loaded (corrupt/invalid existing
        # file), deny rather than allowing arbitrary directory enumeration or
        # creation. A fresh no-file install returns a default config (not None),
        # so the setup flow is unaffected.
        if config is None or not is_path_allowed(path, config):
            return error(
                "Access denied — path outside allowed directories",
                code="PATH_NOT_ALLOWED",
                status_code=403,
            )

        resolved = Path(path).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            return error(
                "Invalid path",
                code="INVALID_PATH",
                status_code=400,
                data={"directories": [], "exists": False, "writable": False},
            )

        dirs = [
            p.name
            for p in resolved.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        dirs.sort()

        return ok(
            f"Listed {len(dirs)} directories",
            {
                "directories": dirs,
                "exists": True,
                "writable": os.access(resolved, os.W_OK),
            },
        )
    except Exception as e:
        logger.error(f"Error listing directory {path}: {e}")
        return error(
            "Error listing directory",
            code="DIRECTORY_LIST_ERROR",
            status_code=500,
        )


@router.post(
    "/folder",
    summary="Create directory",
    description="Creates a new directory at the specified path with parent directory creation.",
    responses={
        200: {
            "description": "Directory created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Folder created",
                        "data": {"path": "/home/user/new-folder"},
                    }
                }
            },
        },
        400: {"description": "Invalid path or directory already exists"},
    },
)
async def create_directory(
    request_data: FolderCreationRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Create a new directory at the specified path.

    Creates parent directories as needed. Used by the UI when
    users need to create directories during configuration.

    Args:
        request_data: Request containing the directory path to create

    Returns:
        Success confirmation with the created path
    """
    try:
        path = request_data.path

        # Restrict to configured allowed roots
        try:
            config = load_config()
        except ConfigError:
            config = None

        # Fail closed: if the config can't be loaded (corrupt/invalid existing
        # file), deny rather than allowing arbitrary directory enumeration or
        # creation. A fresh no-file install returns a default config (not None),
        # so the setup flow is unaffected.
        if config is None or not is_path_allowed(path, config):
            return error(
                "Access denied — path outside allowed directories",
                code="PATH_NOT_ALLOWED",
                status_code=403,
            )

        resolved = Path(path).expanduser().resolve()
        logger.info(f"Creating folder: {resolved}")
        resolved.mkdir(parents=True, exist_ok=False)

        return ok("Folder created", {"path": str(resolved)})
    except FileExistsError:
        logger.warning(f"Folder already exists: {path}")
        return error(
            "Folder already exists",
            code="FOLDER_EXISTS",
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Error creating folder {path}: {e}")
        return error(
            "Error creating folder",
            code="FOLDER_CREATION_ERROR",
            status_code=500,
        )


@router.get(
    "/allowed-roots",
    summary="List allowed filesystem roots",
    description="Returns the absolute paths the directory picker is permitted to browse.",
    responses={
        200: {
            "description": "Allowed roots list",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "2 allowed roots",
                        "data": {"roots": ["/kometa/posters", "/data/media"]},
                    }
                }
            },
        },
    },
)
async def list_allowed_roots(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Return the configured allowed roots for the directory picker."""
    try:
        try:
            config = load_config()
        except ConfigError:
            return ok("0 allowed roots", {"roots": []})

        # The picker only wants top-level directories — file paths and
        # nested subdirs of an already-allowed root just create noise.
        # is_path_allowed() still uses the full get_allowed_roots set,
        # so write checks aren't affected by this filtering.
        roots = sorted({str(p) for p in get_browse_roots(config)})
        return ok(f"{len(roots)} allowed roots", {"roots": roots})
    except Exception as e:
        logger.error(f"Error listing allowed roots: {e}")
        return error(
            "Error listing allowed roots",
            code="ALLOWED_ROOTS_ERROR",
            status_code=500,
        )


_GDRIVE_PRESETS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "gdrive_presets.json"
)
_gdrive_presets_cache: Optional[List[dict]] = None


@router.get(
    "/gdrive-presets",
    summary="List bundled GDrive presets",
    description="Returns the curated list of CL2K and MM2K Google Drive presets bundled with CHUB.",
    responses={
        200: {
            "description": "Preset list",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Loaded 41 presets",
                        "data": [
                            {"name": "Chris DC", "id": "1oBz...", "style": "MM2K"}
                        ],
                    }
                }
            },
        },
    },
)
async def list_gdrive_presets(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Return the bundled GDrive presets JSON (cached after first load)."""
    global _gdrive_presets_cache
    try:
        if _gdrive_presets_cache is None:
            with open(_GDRIVE_PRESETS_PATH, "r", encoding="utf-8") as fh:
                _gdrive_presets_cache = json.load(fh)
        return ok(f"Loaded {len(_gdrive_presets_cache)} presets", _gdrive_presets_cache)
    except FileNotFoundError:
        logger.error(f"GDrive presets file not found at {_GDRIVE_PRESETS_PATH}")
        return error(
            "GDrive presets file not found",
            code="GDRIVE_PRESETS_MISSING",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error loading gdrive presets: {e}")
        return error(
            "Error loading gdrive presets",
            code="GDRIVE_PRESETS_ERROR",
            status_code=500,
        )


@router.post(
    "/test",
    summary="Test endpoint",
    description="Generic test endpoint for API connectivity and payload echo testing.",
    responses={
        200: {
            "description": "Test endpoint response with echoed data",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Test endpoint working",
                        "data": {"received": {"message": "test", "data": None}},
                    }
                }
            },
        },
        400: {"description": "Invalid request data"},
    },
)
async def test(
    request_data: TestEndpointRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Generic test endpoint for API connectivity.

    Echoes back the received data to verify API communication
    and JSON serialization. Used for debugging and health checks.

    Args:
        request_data: Test data to echo back

    Returns:
        Success response with the received data
    """
    logger.debug("Serving POST /api/test")
    try:
        received_data = request_data.model_dump()
        logger.debug(f"Received data: {received_data}")

        return ok("Test endpoint working", {"received": received_data})
    except Exception as e:
        logger.error(f"Error processing test request: {e}")
        return error(
            "Error processing test request",
            code="TEST_ENDPOINT_ERROR",
            status_code=400,
        )


# ==== Backup / Restore ====


@router.post(
    "/backup",
    summary="Create backup",
    description="Creates a zip archive of config.yml and chub.db for download.",
    responses={
        200: {"description": "Backup zip file download"},
        500: {"description": "Backup creation failed"},
    },
)
def create_backup(
    request: Request, logger: Any = Depends(get_logger)
) -> StreamingResponse:
    """
    Create and download a backup zip containing config.yml and chub.db.

    Uses SQLite's backup API to safely copy the database while it may be in use.
    """
    try:
        logger.info("Creating backup...")
        backup_path = save_backup(logger)
        buf = io.BytesIO(backup_path.read_bytes())
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={backup_path.name}"},
        )

    except ConfigError:
        raise  # deny — main.py's handler returns CONFIG_INVALID
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        return error(
            "Backup creation failed",
            code="BACKUP_ERROR",
            status_code=500,
        )


@router.get(
    "/backups",
    summary="List backups",
    description="List available backup files.",
)
async def list_backups(logger: Any = Depends(get_logger)) -> JSONResponse:
    """List backup files in the backups directory."""
    try:
        backup_dir = get_backup_dir()
        backups = []
        for f in sorted(backup_dir.glob("chub-backup-*.zip"), reverse=True):
            stat = f.stat()
            backups.append(
                {
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )
        return ok(f"Found {len(backups)} backups", {"backups": backups})
    except ConfigError:
        raise  # deny — main.py's handler returns CONFIG_INVALID
    except Exception as e:
        logger.error(f"Error listing backups: {e}")
        return error("Error listing backups", code="BACKUP_LIST_ERROR", status_code=500)


@router.post(
    "/restore",
    summary="Restore from backup",
    description="Upload a backup zip to restore config.yml. Database restore requires app restart.",
    responses={
        200: {"description": "Restore completed successfully"},
        400: {"description": "Invalid backup file"},
    },
)
async def restore_backup(
    file: UploadFile = File(...),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Restore from a backup zip.

    Validates the zip, creates a safety backup of current state,
    then restores config.yml. Database SQL dump is saved for manual
    restore if needed (full DB restore requires app restart).
    """
    try:
        # Read in chunks so an oversized upload is rejected without ever
        # holding more than the cap in memory.
        chunks: List[bytes] = []
        received = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > MAX_RESTORE_UPLOAD_BYTES:
                return error(
                    f"Backup upload exceeds the "
                    f"{MAX_RESTORE_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    code="BACKUP_TOO_LARGE",
                    status_code=413,
                )
            chunks.append(chunk)
        content = b"".join(chunks)

        # The zip parse + yaml validation + file writes are blocking; run them
        # off the event loop so a large upload doesn't stall the whole server.
        def _do_restore() -> JSONResponse:
            """Validate the zip and write config.yml back; blocking."""
            buf = io.BytesIO(content)

            if not zipfile.is_zipfile(buf):
                return error(
                    "Uploaded file is not a valid zip",
                    code="INVALID_BACKUP",
                    status_code=400,
                )

            buf.seek(0)
            with zipfile.ZipFile(buf, "r") as zf:
                names = zf.namelist()

                if "config.yml" not in names:
                    return error(
                        "Backup zip must contain config.yml",
                        code="INVALID_BACKUP_CONTENTS",
                        status_code=400,
                    )

                # Reject zip bombs before decompressing anything. zipfile caps
                # each member read at its declared file_size, so the declared
                # size is a trustworthy upper bound on what zf.read() returns.
                member_caps = {
                    "config.yml": MAX_RESTORE_CONFIG_BYTES,
                    "chub.db.sql": MAX_RESTORE_SQL_BYTES,
                }
                for member, cap in member_caps.items():
                    if member in names and zf.getinfo(member).file_size > cap:
                        return error(
                            f"{member} in backup exceeds the "
                            f"{cap // (1024 * 1024)} MB limit",
                            code="BACKUP_MEMBER_TOO_LARGE",
                            status_code=413,
                        )

                # Validate the config.yml inside the zip
                raw_config = zf.read("config.yml")
                import yaml

                try:
                    parsed = yaml.safe_load(raw_config)
                    ChubConfig.model_validate(parsed)
                except Exception as e:
                    logger.error(f"config.yml in backup is invalid: {e}")
                    return error(
                        "config.yml in backup is invalid",
                        code="INVALID_BACKUP_CONFIG",
                        status_code=400,
                    )

                # Safety: backup current state first
                config_path = get_config_path()
                if os.path.exists(config_path):
                    safety_path = config_path + ".pre-restore"
                    with open(config_path, "rb") as src:
                        with open(safety_path, "wb") as dst:
                            dst.write(src.read())

                # Restore config.yml (atomic write)
                restored_config = ChubConfig.model_validate(parsed)
                save_config(restored_config)
                restored_items = ["config.yml"]

                # If DB dump is included, save it for reference
                if "chub.db.sql" in names:
                    backup_dir = get_backup_dir()
                    sql_path = backup_dir / "restored-db.sql"
                    sql_path.write_bytes(zf.read("chub.db.sql"))
                    restored_items.append(
                        "chub.db.sql (saved to backups/restored-db.sql)"
                    )

            logger.info(f"Restore completed: {restored_items}")
            return ok(
                "Restore completed",
                {"restored": restored_items},
            )

        return await run_in_threadpool(_do_restore)

    except ConfigError:
        raise  # deny — main.py's handler returns CONFIG_INVALID
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return error("Restore failed", code="RESTORE_ERROR", status_code=500)


@router.get(
    "/system/health/snapshots",
    summary="Recent instance health snapshots",
    description="Return the most recent periodic health probes written by the "
    "scheduler. For a live probe use /api/instances/health.",
)
async def get_health_snapshots(
    limit: int = 50,
    instance: str = None,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        limit = max(1, min(limit, 500))
        if instance:
            rows = db.worker.execute_query(
                "SELECT * FROM system_health_snapshots WHERE instance_name=? "
                "ORDER BY snapshot_at DESC LIMIT ?",
                (instance, limit),
                fetch_all=True,
            )
        else:
            rows = db.worker.execute_query(
                "SELECT * FROM system_health_snapshots ORDER BY snapshot_at DESC LIMIT ?",
                (limit,),
                fetch_all=True,
            )
        snaps = [dict(r) for r in rows or []]
        return ok(f"Retrieved {len(snaps)} snapshots", {"snapshots": snaps})
    except Exception as e:
        logger.error(f"Error fetching health snapshots: {e}")
        return error(
            "Error fetching health snapshots",
            code="HEALTH_SNAPSHOT_ERROR",
            status_code=500,
        )


@router.get(
    "/system/digest",
    summary="Rolling activity digest",
    description="Aggregate recent activity: media-cache additions, job "
    "success/failure counts, module run states, and latest instance health. "
    "Defaults to the last 7 days; override with ?days=N (1–90).",
)
async def get_system_digest(
    days: int = 7,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    from datetime import timedelta

    try:
        days = max(1, min(days, 90))
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        # Media added in window
        media_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM media_cache WHERE created_at >= ?",
            (cutoff,),
            fetch_one=True,
        )
        media_added = media_row["total"] if media_row else 0

        # Job stats in window
        job_rows = db.worker.execute_query(
            "SELECT status, COUNT(*) AS total FROM jobs WHERE received_at >= ? GROUP BY status",
            (cutoff,),
            fetch_all=True,
        )
        job_counts = {r["status"]: r["total"] for r in job_rows or []}

        # Failed module runs in window, with module names
        failed_runs = db.worker.execute_query(
            "SELECT id, type, payload, error, received_at FROM jobs "
            "WHERE status='error' AND received_at >= ? "
            "ORDER BY received_at DESC LIMIT 20",
            (cutoff,),
            fetch_all=True,
        )
        recent_failures = []
        import json as _json

        for r in failed_runs or []:
            payload = r["payload"]
            try:
                payload = _json.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                payload = {}
            recent_failures.append(
                {
                    "id": r["id"],
                    "type": r["type"],
                    "module_name": (payload or {}).get("module_name"),
                    "error": r["error"],
                    "received_at": r["received_at"],
                }
            )

        # Latest health per instance
        health_rows = db.worker.execute_query(
            """
            SELECT s.instance_name, s.service, s.status, s.response_time_ms,
                   s.status_code, s.snapshot_at, s.error
            FROM system_health_snapshots s
            INNER JOIN (
              SELECT instance_name, MAX(snapshot_at) AS latest
              FROM system_health_snapshots GROUP BY instance_name
            ) latest ON s.instance_name = latest.instance_name
                    AND s.snapshot_at = latest.latest
            """,
            fetch_all=True,
        )
        latest_health = [dict(r) for r in health_rows or []]

        return ok(
            f"Digest for last {days}d",
            {
                "window_days": days,
                "media_added": media_added,
                "job_counts": job_counts,
                "recent_failures": recent_failures,
                "latest_instance_health": latest_health,
            },
        )
    except Exception as e:
        logger.error(f"Error building digest: {e}")
        return error(
            "Error building digest",
            code="DIGEST_ERROR",
            status_code=500,
        )


@router.get(
    "/system/cleanup-candidates",
    summary="Cleanup candidates report",
    description="Surface items worth cleaning up: old errored jobs, stale "
    "scan cache entries, unmatched media/collections counts. Read-only — no mutations.",
)
async def get_cleanup_candidates(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        old_jobs_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM jobs WHERE status='error'",
            fetch_one=True,
        )
        unmatched_media_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM media_cache WHERE matched=0",
            fetch_one=True,
        )
        unmatched_coll_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM collections_cache WHERE matched=0",
            fetch_one=True,
        )
        return ok(
            "Cleanup candidates",
            {
                "errored_jobs": old_jobs_row["total"] if old_jobs_row else 0,
                "unmatched_media": unmatched_media_row["total"]
                if unmatched_media_row
                else 0,
                "unmatched_collections": unmatched_coll_row["total"]
                if unmatched_coll_row
                else 0,
            },
        )
    except Exception as e:
        logger.error(f"Error building cleanup candidates: {e}")
        return error(
            "Error building cleanup candidates",
            code="CLEANUP_CANDIDATES_ERROR",
            status_code=500,
        )


# Tables listed in db-stats / vacuum responses. Kept explicit instead of
# enumerating sqlite_master so we don't surface internal SQLite tables
# (sqlite_sequence, sqlite_stat1) that users have no reason to see.
_DB_STATS_TABLES = (
    "media_cache",
    "poster_cache",
    "collections_cache",
    "plex_media_cache",
    "jobs",
    "webhook_cache",
    "gdrive_stats",
    "scan_cache",
    "system_health_snapshots",
    "media_edit_history",
    "upgradinatorr_progress",
    "poster_collections",
    "poster_collection_items",
    "holiday_status",
    "run_state",
    "schema_migrations",
)


@router.get(
    "/system/db-stats",
    summary="Database statistics",
    description="Per-table row counts plus SQLite page/freelist info and the "
    "schema_migrations log. Read-only.",
)
async def get_db_stats(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving GET /api/system/db-stats")
        tables = []
        existing = {
            row["name"]
            for row in (
                db.worker.execute_query(
                    "SELECT name FROM sqlite_master WHERE type='table'",
                    fetch_all=True,
                )
                or []
            )
        }
        for name in _DB_STATS_TABLES:
            if name not in existing:
                continue
            count_row = db.worker.execute_query(
                f"SELECT COUNT(*) AS total FROM {name}", fetch_one=True
            )
            tables.append(
                {"name": name, "rows": count_row["total"] if count_row else 0}
            )

        page_size_row = db.worker.execute_query("PRAGMA page_size", fetch_one=True)
        page_count_row = db.worker.execute_query("PRAGMA page_count", fetch_one=True)
        freelist_row = db.worker.execute_query("PRAGMA freelist_count", fetch_one=True)
        page_size = int(page_size_row["page_size"]) if page_size_row else 0
        page_count = int(page_count_row["page_count"]) if page_count_row else 0
        freelist_count = int(freelist_row["freelist_count"]) if freelist_row else 0
        total_bytes = page_size * page_count
        free_bytes = page_size * freelist_count

        try:
            file_bytes = os.path.getsize(db.db_path)
        except OSError:
            file_bytes = total_bytes

        migrations = []
        if "schema_migrations" in existing:
            migrations = (
                db.worker.execute_query(
                    "SELECT name, applied_at FROM schema_migrations ORDER BY applied_at DESC, name DESC",
                    fetch_all=True,
                )
                or []
            )

        return ok(
            "Database statistics",
            {
                "tables": tables,
                "page_size": page_size,
                "page_count": page_count,
                "freelist_count": freelist_count,
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "file_bytes": file_bytes,
                "schema_migrations": migrations,
            },
        )
    except Exception as e:
        logger.error(f"Error building db stats: {e}")
        return error(
            "Error building db stats",
            code="DB_STATS_ERROR",
            status_code=500,
        )


@router.post(
    "/system/db/vacuum",
    summary="Compact database (SQLite VACUUM)",
    description="Reclaims space freed by deletions and updates. Safe to run "
    "any time but holds a write lock for the duration — short on a small "
    "DB (~1s for 50MB), longer if your DB has grown.",
)
def vacuum_database(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/system/db/vacuum")
        try:
            bytes_before = os.path.getsize(db.db_path)
        except OSError:
            bytes_before = 0

        # VACUUM cannot run inside an explicit transaction and ignores the
        # connection's normal isolation; bypass the worker's helper and use
        # a raw sqlite3 connection scoped to this call.
        start = time.time()
        conn = sqlite3.connect(db.db_path, timeout=60)
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
        finally:
            conn.close()
        duration_ms = int((time.time() - start) * 1000)

        try:
            bytes_after = os.path.getsize(db.db_path)
        except OSError:
            bytes_after = bytes_before

        reclaimed = max(0, bytes_before - bytes_after)
        logger.info(
            f"VACUUM completed in {duration_ms}ms — reclaimed {reclaimed} bytes "
            f"({bytes_before} -> {bytes_after})"
        )
        return ok(
            "Database compacted",
            {
                "bytes_before": bytes_before,
                "bytes_after": bytes_after,
                "bytes_reclaimed": reclaimed,
                "duration_ms": duration_ms,
            },
        )
    except Exception as e:
        logger.error(f"Error running VACUUM: {e}")
        return error(
            "Error running VACUUM",
            code="DB_VACUUM_ERROR",
            status_code=500,
        )


@router.post(
    "/system/db/poster-cache/clear",
    summary="Wipe poster_cache for a full rescan",
    description="Deletes every row in poster_cache. The next poster_renamerr "
    "run does a fresh scan of all source_dirs and re-populates the table. "
    "Use when a code change has affected how posters are parsed or matched "
    "and orphan rows might be lingering.",
)
async def clear_poster_cache(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/system/db/poster-cache/clear")
        # Serialize against poster_renamerr's clear()+rebuild+match critical
        # section so a manual wipe can't empty the cache mid-run.
        from backend.modules.poster_renamerr import _POSTER_CACHE_REBUILD_LOCK

        with _POSTER_CACHE_REBUILD_LOCK:
            count_row = db.worker.execute_query(
                "SELECT COUNT(*) AS total FROM poster_cache", fetch_one=True
            )
            before = int(count_row["total"]) if count_row else 0

            db.poster.clear()

        logger.info(
            f"Wiped poster_cache via /api/system/db/poster-cache/clear ({before} rows)"
        )
        return ok(
            "Poster cache cleared",
            {"deleted": before},
        )
    except Exception as e:
        logger.error(f"Error clearing poster_cache: {e}")
        return error(
            "Error clearing poster_cache",
            code="DB_CLEAR_POSTER_CACHE_ERROR",
            status_code=500,
        )


@router.post(
    "/system/db/artwork-matches/clear",
    summary="Reset additional-artwork match state",
    description="Deletes every row in media_asset_matches (logo/background/"
    "square-art apply provenance + per-type ignore flags). The Additional-"
    "artwork coverage view resets to all-missing; the next asset_renamerr run "
    "repopulates it from real apply results. Use to purge stale state — e.g. "
    "rows a pre-fix dry-run wrongly recorded as 'applied'. Does not touch "
    "posters or media_cache.",
)
async def clear_artwork_matches(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/system/db/artwork-matches/clear")
        count_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM media_asset_matches", fetch_one=True
        )
        before = int(count_row["total"]) if count_row else 0

        db.media_asset_matches.clear()

        logger.info(
            f"Wiped media_asset_matches via /api/system/db/artwork-matches/clear "
            f"({before} rows)"
        )
        return ok("Artwork match state cleared", {"deleted": before})
    except Exception as e:
        logger.error(f"Error clearing media_asset_matches: {e}")
        return error(
            "Error clearing media_asset_matches",
            code="DB_CLEAR_ARTWORK_MATCHES_ERROR",
            status_code=500,
        )


@router.post(
    "/system/db/poster-matches/reset",
    summary="Reset poster-match coverage to all-missing",
    description="Resets the Unmatched page's poster figures: clears the "
    "matched flag + match metadata (status/confidence/reason + matched poster "
    "file/timestamp) for media and collections, so the next poster_renamerr "
    "run re-matches from scratch. Preserves user-curated rows — ignored "
    "(dismissed) and locked (user_confirmed) — and the Plex identity mapping. "
    "Does not touch posters on disk or media_asset_matches (additional "
    "artwork).",
)
async def reset_poster_matches(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/system/db/poster-matches/reset")
        media_reset = db.media.reset_match_state()
        collection_reset = db.collection.reset_match_state()
        total = media_reset + collection_reset
        logger.info(
            "Reset poster-match coverage via /api/system/db/poster-matches/reset "
            f"({media_reset} media + {collection_reset} collection rows; "
            "ignored/locked preserved)"
        )
        return ok(
            "Poster match coverage reset",
            {
                "reset": total,
                "media": media_reset,
                "collections": collection_reset,
            },
        )
    except Exception as e:
        logger.error(f"Error resetting poster match state: {e}")
        return error(
            "Error resetting poster match state",
            code="DB_RESET_POSTER_MATCHES_ERROR",
            status_code=500,
        )


@router.post(
    "/system/db/artwork-matches/reset",
    summary="Reset additional-artwork coverage (preserving ignores)",
    description="Resets the Unmatched page's additional-artwork figures: drops "
    "every applied/failed row in media_asset_matches so coverage returns to "
    "all-missing and the next asset_renamerr run repopulates it. Unlike "
    "artwork-matches/clear, this PRESERVES the per-type 'not needed' (ignored) "
    "flags the user set.",
)
async def reset_artwork_matches(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/system/db/artwork-matches/reset")
        count_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM media_asset_matches "
            "WHERE ignored IS NULL OR ignored = 0",
            fetch_one=True,
        )
        before = int(count_row["total"]) if count_row else 0

        db.media_asset_matches.clear(keep_ignored=True)

        logger.info(
            "Reset additional-artwork coverage via "
            f"/api/system/db/artwork-matches/reset ({before} rows; ignores kept)"
        )
        return ok("Artwork match coverage reset", {"deleted": before})
    except Exception as e:
        logger.error(f"Error resetting artwork match state: {e}")
        return error(
            "Error resetting artwork match state",
            code="DB_RESET_ARTWORK_MATCHES_ERROR",
            status_code=500,
        )
