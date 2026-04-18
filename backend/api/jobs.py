import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.database import ChubDB


def _enrich_jobs(jobs):
    """Extract module_name from payload for module_run jobs."""
    for job in jobs:
        if job.get("type") == "module_run" and job.get("payload"):
            payload = job["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
            if isinstance(payload, dict):
                job["module_name"] = payload.get("module_name", "")
    return jobs

router = APIRouter(
    prefix="/api",
    tags=["Jobs"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Job not found"},
    },
)


@router.get("/jobs/stats")
async def get_job_stats(
    logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> Dict[str, Any]:
    """Retrieve job statistics."""
    try:
        result = db.worker.job_stats("jobs", error_limit=10)

        if isinstance(result, dict) and "success" in result:
            return result
        else:
            return ok("Job statistics retrieved", result if result else {"stats": {}})

    except Exception as e:
        logger.error(f"Error fetching job stats: {e}")
        return error(
            f"Error retrieving job statistics: {str(e)}",
            "JOB_STATS_ERROR",
            status_code=500,
        )


@router.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    module: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Dict[str, Any]:
    """
    List jobs with optional filters and pagination.

    Filters:
    - status: pending / running / success / error / cancelled
    - job_type: module_run / webhook / sync_gdrive / etc.
    - module: module_name (applies to module_run jobs)
    """
    try:
        # Clamp to avoid accidental massive fetches.
        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        result = db.worker.list_jobs(
            status=status,
            limit=limit,
            offset=offset,
            job_type=job_type,
            module_name=module,
        )

        if isinstance(result, dict) and "success" in result:
            jobs = result.get("data", {}).get("jobs", [])
            _enrich_jobs(jobs)
            return result
        return ok(
            f"Retrieved jobs list (limit: {limit})",
            result if result else {"jobs": []},
        )

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        return error(
            f"Error listing jobs: {str(e)}", code="JOBS_LIST_ERROR", status_code=500
        )


@router.get("/jobs/webhook-origins")
async def list_webhook_origins(
    days: int = 7,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Dict[str, Any]:
    """
    Summarize webhook jobs in the last N days by origin (client_host + endpoint)
    and status. Helpful for spotting a noisy Sonarr instance or a dead webhook.
    """
    from datetime import datetime, timedelta

    try:
        days = max(1, min(days, 90))
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = db.worker.execute_query(
            "SELECT id, payload, status, received_at FROM jobs "
            "WHERE type='webhook' AND received_at >= ? ORDER BY received_at DESC",
            (cutoff,),
            fetch_all=True,
        ) or []
        from collections import Counter

        by_origin: Counter = Counter()
        by_status: Counter = Counter()
        for r in rows:
            payload = r["payload"]
            try:
                payload = json.loads(payload) if isinstance(payload, str) else payload
            except Exception:
                payload = {}
            origin = (payload or {}).get("origin", {}) or {}
            key = (
                origin.get("client_host") or "unknown",
                origin.get("endpoint") or "unknown",
            )
            by_origin[key] += 1
            by_status[r["status"]] += 1
        return ok(
            f"Webhook origins in last {days}d",
            {
                "total": len(rows),
                "by_origin": [
                    {"client_host": h, "endpoint": e, "count": c}
                    for (h, e), c in by_origin.most_common()
                ],
                "by_status": dict(by_status),
            },
        )
    except Exception as e:
        logger.error(f"Error summarizing webhook origins: {e}")
        return error(
            f"Error summarizing webhook origins: {str(e)}",
            code="WEBHOOK_ORIGIN_ERROR",
            status_code=500,
        )


@router.delete("/jobs/old")
async def delete_old_jobs(
    days: int = 30,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Dict[str, Any]:
    """Delete completed/errored jobs older than `days` (default 30)."""
    days = max(1, min(days, 365))
    try:
        result = db.worker.cleanup_jobs("jobs", days=days)
        if isinstance(result, dict) and "success" in result:
            return result
        return ok(f"Cleaned up jobs older than {days}d", result or {})
    except Exception as e:
        logger.error(f"Error cleaning up jobs: {e}")
        return error(
            f"Error cleaning up jobs: {str(e)}",
            code="JOBS_CLEANUP_ERROR",
            status_code=500,
        )


@router.get("/jobs/{job_id}")
async def get_job_detail(
    job_id: int, logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> Dict[str, Any]:
    """Retrieve job details by ID."""
    try:
        job = db.worker.get_job_by_id("jobs", job_id)

        if not job:
            return error(f"Job {job_id} not found", "JOB_NOT_FOUND", status_code=404)

        return ok(f"Job {job_id} details retrieved", {"job": job})

    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}")
        return error(
            f"Error retrieving job details: {str(e)}",
            "JOB_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.get("/jobs/{job_id}/log-tail")
async def get_job_log_tail(
    job_id: int,
    offset: int = 0,
    max_bytes: int = 65536,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> Dict[str, Any]:
    """
    Tail the log file of the module associated with this job.

    Polled by the live-progress modal every ~1s. Returns new bytes since the
    caller's `offset` plus a `next_offset` for the next call. `max_bytes`
    caps per-response size so a runaway logger can't blow up the client.
    """
    try:
        import os

        job = db.worker.get_job_by_id("jobs", job_id)
        if not job:
            return error(f"Job {job_id} not found", "JOB_NOT_FOUND", status_code=404)

        payload = job.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        module_name = (payload or {}).get("module_name") if isinstance(payload, dict) else None
        if not module_name:
            return ok(
                "No module log for this job type",
                {"lines": "", "next_offset": offset, "status": job.get("status")},
            )

        # Allow-list check: even though module_name is stored in our DB rather
        # than read directly from the request, a malformed payload shouldn't
        # be able to cause os.path.join to resolve outside the logs dir.
        from backend.modules import MODULES

        if module_name not in MODULES and module_name != "general":
            return ok(
                "Unknown module",
                {"lines": "", "next_offset": offset, "status": job.get("status")},
            )

        # Match backend/util/logger.py:_get_log_path fallback logic so dev
        # environments without LOG_DIR still find the right file.
        log_base = os.environ.get("LOG_DIR")
        if log_base:
            log_path = os.path.join(log_base, module_name, f"{module_name}.log")
        else:
            repo_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            log_path = os.path.join(repo_root, "logs", module_name, f"{module_name}.log")
        if not os.path.isfile(log_path):
            return ok(
                "Log file not yet present",
                {"lines": "", "next_offset": offset, "status": job.get("status")},
            )

        size = os.path.getsize(log_path)
        if offset > size:
            offset = 0  # file rotated
        chunk = b""
        if size > offset:
            with open(log_path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read(min(max_bytes, size - offset))
        return ok(
            "Log tail",
            {
                "lines": chunk.decode("utf-8", errors="replace"),
                "next_offset": offset + len(chunk),
                "status": job.get("status"),
                "module": module_name,
            },
        )
    except Exception as e:
        logger.error(f"Error tailing log for job {job_id}: {e}")
        return error(
            f"Error tailing log: {str(e)}", "LOG_TAIL_ERROR", status_code=500
        )


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int, logger: Any = Depends(get_logger), db: ChubDB = Depends(get_database)
) -> Dict[str, Any]:
    """Retry a failed job by resetting it to pending status."""
    try:
        success = db.worker.reset_job_to_pending("jobs", job_id)

        if success is None:
            return error(f"Job {job_id} not found", "JOB_NOT_FOUND", status_code=404)
        elif success is False:
            return error(
                "Job cannot be retried (not in error/success state)",
                "JOB_RETRY_INVALID_STATE",
                status_code=400,
            )
        else:
            logger.info(f"Job {job_id} reset to pending for retry")
            return ok(
                f"Job {job_id} queued for retry",
                {"job_id": job_id, "status": "pending"},
            )

    except Exception as e:
        logger.error(f"Error retrying job {job_id}: {e}")
        return error(
            f"Error retrying job: {str(e)}", "JOB_RETRY_ERROR", status_code=500
        )
