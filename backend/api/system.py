"""
System-level API endpoints for CHUB.

Provides core system functionality including version information,
directory operations, and testing utilities.
"""

import io
import os
import shutil
import sqlite3
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.config import ConfigError, ChubConfig, get_config_path, load_config, save_config
from backend.util.database import ChubDB
from backend.util.path_safety import is_path_allowed
from backend.util.version import get_version

router = APIRouter(
    prefix="/api",
    tags=["System"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Bad request"},
    },
)


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
            f"Error getting version: {str(e)}", code="VERSION_ERROR", status_code=500
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
            stats = worker.get_worker_stats() if hasattr(worker, "get_worker_stats") else {}
            checks[name] = stats.get("status", "unknown")
            if stats.get("status") != "running":
                status = "degraded"

    # Database health
    db = getattr(request.app.state, "db", None)
    if db:
        try:
            db.execute_query("SELECT 1")
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
    for path in targets:
        entry: dict[str, Any] = {"path": path, "exists": os.path.isdir(path)}
        if entry["exists"]:
            try:
                usage = shutil.disk_usage(path)
                entry["total_bytes"] = usage.total
                entry["used_bytes"] = usage.used
                entry["free_bytes"] = usage.free
                entry["percent_used"] = round((usage.used / usage.total) * 100, 1)
            except OSError as exc:
                entry["error"] = str(exc)
        out.append(entry)
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

        if config and not is_path_allowed(path, config):
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
            f"Error listing directory: {str(e)}",
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

        if config and not is_path_allowed(path, config):
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
            f"Error creating folder: {str(e)}",
            code="FOLDER_CREATION_ERROR",
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
            f"Error processing test request: {str(e)}",
            code="TEST_ENDPOINT_ERROR",
            status_code=400,
        )


# ==== Backup / Restore ====


def _get_db_path() -> str:
    """Get the SQLite database path."""
    config_dir = os.environ.get("CONFIG_DIR") or str(
        Path(__file__).parents[2] / "config"
    )
    return os.path.join(config_dir, "chub.db")


def _get_backup_dir() -> Path:
    """Get (and create) the backup directory."""
    config_dir = os.environ.get("CONFIG_DIR") or str(
        Path(__file__).parents[2] / "config"
    )
    backup_dir = Path(config_dir) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


@router.post(
    "/backup",
    summary="Create backup",
    description="Creates a zip archive of config.yml and chub.db for download.",
    responses={
        200: {"description": "Backup zip file download"},
        500: {"description": "Backup creation failed"},
    },
)
async def create_backup(
    request: Request, logger: Any = Depends(get_logger)
) -> StreamingResponse:
    """
    Create and download a backup zip containing config.yml and chub.db.

    Uses SQLite's backup API to safely copy the database while it may be in use.
    """
    try:
        logger.info("Creating backup...")

        config_path = get_config_path()
        db_path = _get_db_path()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add config.yml
            if os.path.exists(config_path):
                zf.write(config_path, "config.yml")

            # Safely copy SQLite database using backup API
            if os.path.exists(db_path):
                db_buf = io.BytesIO()
                src = sqlite3.connect(db_path)
                try:
                    mem = sqlite3.connect(":memory:")
                    src.backup(mem)
                    # Dump from memory to bytes
                    for line in mem.iterdump():
                        db_buf.write(f"{line}\n".encode("utf-8"))
                    mem.close()
                finally:
                    src.close()
                db_buf.seek(0)
                zf.writestr("chub.db.sql", db_buf.read())

        buf.seek(0)
        filename = f"chub-backup-{timestamp}.zip"

        # Also save a copy to the backups directory
        backup_dir = _get_backup_dir()
        backup_path = backup_dir / filename
        backup_path.write_bytes(buf.getvalue())
        buf.seek(0)

        logger.info(f"Backup created: {filename}")
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        return error(
            f"Backup creation failed: {str(e)}",
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
        backup_dir = _get_backup_dir()
        backups = []
        for f in sorted(backup_dir.glob("chub-backup-*.zip"), reverse=True):
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        return ok(f"Found {len(backups)} backups", {"backups": backups})
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
        content = await file.read()
        buf = io.BytesIO(content)

        if not zipfile.is_zipfile(buf):
            return error("Uploaded file is not a valid zip", code="INVALID_BACKUP", status_code=400)

        buf.seek(0)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()

            if "config.yml" not in names:
                return error(
                    "Backup zip must contain config.yml",
                    code="INVALID_BACKUP_CONTENTS",
                    status_code=400,
                )

            # Validate the config.yml inside the zip
            raw_config = zf.read("config.yml")
            import yaml
            try:
                parsed = yaml.safe_load(raw_config)
                ChubConfig.model_validate(parsed)
            except Exception as e:
                return error(
                    f"config.yml in backup is invalid: {e}",
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
                backup_dir = _get_backup_dir()
                sql_path = backup_dir / "restored-db.sql"
                sql_path.write_bytes(zf.read("chub.db.sql"))
                restored_items.append("chub.db.sql (saved to backups/restored-db.sql)")

        logger.info(f"Restore completed: {restored_items}")
        return ok(
            "Restore completed",
            {"restored": restored_items},
        )

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
            f"Error fetching health snapshots: {str(e)}",
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

        # Orphaned posters count (space recoverable signal)
        orphaned_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM orphaned_posters", fetch_one=True
        )
        orphaned_count = orphaned_row["total"] if orphaned_row else 0

        return ok(
            f"Digest for last {days}d",
            {
                "window_days": days,
                "media_added": media_added,
                "job_counts": job_counts,
                "recent_failures": recent_failures,
                "latest_instance_health": latest_health,
                "orphaned_posters": orphaned_count,
            },
        )
    except Exception as e:
        logger.error(f"Error building digest: {e}")
        return error(
            f"Error building digest: {str(e)}",
            code="DIGEST_ERROR",
            status_code=500,
        )


@router.get(
    "/system/cleanup-candidates",
    summary="Cleanup candidates report",
    description="Surface items worth cleaning up: orphaned posters, old "
    "errored jobs, stale scan cache entries. Read-only — no mutations.",
)
async def get_cleanup_candidates(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    try:
        orphaned_row = db.worker.execute_query(
            "SELECT COUNT(*) AS total FROM orphaned_posters", fetch_one=True
        )
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
                "orphaned_posters": orphaned_row["total"] if orphaned_row else 0,
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
            f"Error building cleanup candidates: {str(e)}",
            code="CLEANUP_CANDIDATES_ERROR",
            status_code=500,
        )
