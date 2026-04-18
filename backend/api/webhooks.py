"""
Webhook processing API endpoints for CHUB.

Provides webhook handling for automated poster processing,
media event notifications, and external service integrations.
"""

import hashlib
import hmac
import json
import threading
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.config import ConfigError, load_config
from backend.util.database import ChubDB


def verify_webhook_secret(request: Request) -> None:
    """
    Optionally verify the configured webhook secret on inbound webhook
    requests. Matches Sonarr/Radarr behaviour: if `general.webhook_secret`
    is unset, webhooks are accepted unauthenticated. If it is set, callers
    must send it via `X-Webhook-Secret` header or `?secret=` query param.
    """
    try:
        cfg = load_config()
    except ConfigError:
        return  # Config unavailable — let the endpoint fail naturally.

    expected = (cfg.general.webhook_secret or "").strip()
    if not expected:
        return  # Not configured → no check (local-first default).

    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get(
        "secret", ""
    )
    if not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

# API-layer webhook deduplication
_webhook_cache: Dict[str, float] = {}
_webhook_cache_lock = threading.Lock()
_WEBHOOK_DEBOUNCE_SECONDS = 5

router = APIRouter(
    prefix="/api/webhooks",
    tags=["Webhooks"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Invalid webhook payload"},
    },
)


def get_webhook_logger(request: Request) -> Any:
    """Get webhook-specific logger adapter from app state."""
    return request.app.state.logger.get_adapter("WEBHOOK")


@router.post(
    "/poster/add",
    summary="Process poster webhook",
    description="Handle webhook events for automated poster renaming and upload processing.",
    responses={
        200: {
            "description": "Webhook processed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Webhook enqueued for processing",
                        "data": {"job_id": 123, "status": "enqueued"},
                    }
                }
            },
        },
        400: {"description": "Invalid webhook payload or processing error"},
        401: {"description": "Invalid webhook secret"},
    },
)
async def process_poster_webhook(
    request: Request,
    logger: Any = Depends(get_webhook_logger),
    db: ChubDB = Depends(get_database),
    _secret: None = Depends(verify_webhook_secret),
) -> JSONResponse:
    """
    Process webhook events for automated poster management.

    Handles webhook events from external services (like Radarr/Sonarr)
    for automated poster renaming and upload processing. Creates
    background jobs for the ADHOC poster processing workflow.

    The webhook payload is analyzed to extract media information
    and trigger appropriate poster processing operations.

    Returns:
        Job ID for tracking webhook processing status
    """
    try:
        logger.debug("Serving POST /api/webhooks/poster/add")

        # Extract client information for logging and debugging
        client_info = {
            "client_host": request.client.host if request.client else None,
            "client_port": request.headers.get("X-Service-Port"),
            "headers": dict(request.headers),
            "scheme": getattr(request.url, "scheme", "http"),
        }

        # Parse webhook payload
        data = await request.json()

        # Check for test events and handle them specially
        if _is_test_event(data):
            logger.info(
                f"Test event received from {client_info['scheme']}://{client_info['client_host']}:{client_info['client_port']}"
            )
            return ok(
                "Test webhook received successfully",
                {"event_type": "test"},
            )

        # Deduplicate at API layer before enqueuing
        if _is_duplicate_webhook(data, logger):
            return ok(
                "Duplicate webhook ignored",
                {"duplicate": True, "status": "debounced"},
            )

        # Create job payload with webhook data, client info, and explicit
        # origin metadata so the jobs table can answer "which source fired
        # this webhook" without re-parsing client_info downstream.
        origin = {
            "source": "webhook",
            "endpoint": "poster/add",
            "client_host": client_info.get("client_host"),
            "event_type": data.get("eventType", ""),
            "user_agent": request.headers.get("User-Agent", ""),
        }
        job_data = {
            "webhook_data": data,
            "client_info": client_info,
            "origin": origin,
        }

        # Enqueue webhook processing job
        result = db.worker.enqueue_job("jobs", job_data, job_type="webhook")

        if not result.get("success"):
            logger.error(f"Error persisting webhook: {result.get('message')}")
            return error(
                f"Error enqueuing webhook: {result.get('message', 'Unknown error')}",
                code="WEBHOOK_ENQUEUE_ERROR",
                status_code=result.get("status", 500),
            )

        job_id = result.get("data", {}).get("job_id")
        logger.info(f"Webhook job enqueued - processing job ID: {job_id}")

        return ok(
            "Webhook enqueued for processing",
            {"job_id": job_id, "status": "enqueued"},
        )

    except Exception as e:
        logger.error(f"Exception in webhook processing: {e}", exc_info=True)
        return error(
            f"Webhook processing error: {str(e)}",
            code="WEBHOOK_PROCESSING_ERROR",
            status_code=500,
        )


def _is_duplicate_webhook(data: Dict[str, Any], logger: Any = None) -> bool:
    """
    Check if this webhook is a duplicate using content hashing and debouncing.

    Creates a SHA-256 hash of the media-identifying fields and checks
    against a time-windowed cache to prevent duplicate job enqueueing.
    """
    # Extract media identifiers for hashing
    media_block = data.get("series") or data.get("movie") or {}
    hash_fields = {
        "title": media_block.get("title", ""),
        "year": str(media_block.get("year", "")),
        "tmdb_id": str(media_block.get("tmdbId", "")),
        "tvdb_id": str(media_block.get("tvdbId", "")),
        "imdb_id": str(media_block.get("imdbId", "")),
        "event_type": data.get("eventType", ""),
    }

    content_hash = hashlib.sha256(
        json.dumps(hash_fields, sort_keys=True).encode()
    ).hexdigest()[:16]

    now = time.time()

    with _webhook_cache_lock:
        # Clean up old entries
        expired = [k for k, v in _webhook_cache.items() if now - v > 30]
        for k in expired:
            del _webhook_cache[k]

        # Check for duplicate
        if content_hash in _webhook_cache:
            elapsed = now - _webhook_cache[content_hash]
            if elapsed < _WEBHOOK_DEBOUNCE_SECONDS:
                if logger:
                    logger.debug(
                        f"Duplicate webhook debounced (hash={content_hash}, {elapsed:.1f}s ago)"
                    )
                return True

        _webhook_cache[content_hash] = now

    return False


def _is_test_event(data: Dict[str, Any]) -> bool:
    """
    Check if webhook data represents a test event.

    Analyzes the webhook payload to determine if it's a test
    event sent by external services for connectivity validation.

    Args:
        data: Webhook payload data

    Returns:
        True if this is a test event, False otherwise
    """
    event_type = data.get("eventType", "")
    return isinstance(event_type, str) and "test" in event_type.lower()


@router.get(
    "/unmatched/status",
    summary="Get unmatched assets status",
    description="Retrieve current unmatched asset counts and summary statistics.",
    responses={
        200: {
            "description": "Unmatched assets status retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Unmatched assets status retrieved",
                        "data": {"total": 12, "by_type": {}},
                    }
                }
            },
        }
    },
)
async def get_unmatched_webhook_status(
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve unmatched assets statistics.

    Returns current unmatched asset counts and summary data
    from the unmatched assets module.

    Returns:
        Unmatched assets summary with counts by category
    """
    try:
        logger.debug("Serving GET /api/webhooks/unmatched/status")
        from backend.modules.unmatched_assets import UnmatchedAssets

        adapter = logger.get_adapter("UnmatchedStatus")
        unmatched = UnmatchedAssets(logger=adapter)
        stats = unmatched.get_stats_adhoc()

        return ok(
            "Unmatched assets status retrieved",
            {"summary": stats.get("summary", {}), "status": "active"},
        )
    except Exception as e:
        logger.error(f"Error retrieving unmatched status: {e}")
        return error(
            f"Error retrieving unmatched status: {str(e)}",
            code="UNMATCHED_STATUS_ERROR",
            status_code=500,
        )


@router.post(
    "/unmatched/process",
    summary="Process unmatched assets",
    description="Enqueue an unmatched assets scan to refresh the report.",
    responses={
        200: {
            "description": "Unmatched assets processing enqueued",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Unmatched assets processing enqueued",
                        "data": {"job_id": "abc123"},
                    }
                }
            },
        },
        401: {"description": "Invalid webhook secret"},
    },
)
async def process_unmatched_webhook(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
    _secret: None = Depends(verify_webhook_secret),
) -> JSONResponse:
    """
    Trigger unmatched assets processing.

    Enqueues an unmatched_assets module run to refresh
    the unmatched media report.

    Returns:
        Job ID for tracking the processing operation
    """
    try:
        logger.debug("Serving POST /api/webhooks/unmatched/process")

        result = db.worker.enqueue_job(
            "jobs", {"module_name": "unmatched_assets"}, job_type="module_run"
        )
        if result.get("success"):
            job_id = result.get("data", {}).get("job_id")
            return ok("Unmatched assets processing initiated", {"job_id": job_id})
        return error(
            "Error enqueuing unmatched processing",
            code="UNMATCHED_PROCESS_ERROR",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error processing unmatched webhook: {e}")
        return error(
            f"Error processing unmatched webhook: {str(e)}",
            code="UNMATCHED_PROCESS_ERROR",
            status_code=500,
        )


@router.get(
    "/cleanarr/status",
    summary="Get orphaned poster status",
    description="Retrieve counts of orphaned posters tracked for cleanup.",
    responses={
        200: {
            "description": "Orphaned poster status retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Orphaned poster status retrieved",
                        "data": {"orphaned_count": 5},
                    }
                }
            },
        }
    },
)
async def get_cleanarr_webhook_status(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve orphaned poster cleanup status.

    Returns the current count and details of orphaned posters
    that are tracked for cleanup by the cleanarr system.

    Returns:
        Orphaned poster count and summary
    """
    try:
        logger.debug("Serving GET /api/webhooks/cleanarr/status")

        report = db.orphaned.report_orphaned_posters()

        return ok(
            "Cleanarr status retrieved",
            {
                "orphaned_count": report.get("total", 0),
                "summary": report.get("summary", {}),
                "status": "active",
            },
        )
    except Exception as e:
        logger.error(f"Error retrieving cleanarr status: {e}")
        return error(
            f"Error retrieving cleanarr status: {str(e)}",
            code="CLEANARR_STATUS_ERROR",
            status_code=500,
        )


@router.post(
    "/cleanarr/process",
    summary="Process orphaned poster cleanup",
    description="Trigger cleanup of orphaned poster files from disk and database.",
    responses={
        200: {
            "description": "Cleanup processing completed",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Cleanup completed",
                        "data": {"removed": 3},
                    }
                }
            },
        },
        401: {"description": "Invalid webhook secret"},
    },
)
async def process_cleanarr_webhook(
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
    _secret: None = Depends(verify_webhook_secret),
) -> JSONResponse:
    """
    Trigger orphaned poster cleanup.

    Runs the cleanarr process which deletes orphaned poster files
    from disk and removes their tracking records from the database.

    Returns:
        Cleanup result with count of processed orphaned posters
    """
    try:
        logger.debug("Serving POST /api/webhooks/cleanarr/process")

        cleanarr_logger = logger.get_adapter("CLEANARR")
        db.orphaned.handle_orphaned_posters(cleanarr_logger, dry_run=False)

        return ok("Cleanarr processing completed", {"status": "completed"})
    except Exception as e:
        logger.error(f"Error processing cleanarr webhook: {e}")
        return error(
            f"Error processing cleanarr: {str(e)}",
            code="CLEANARR_PROCESS_ERROR",
            status_code=500,
        )
