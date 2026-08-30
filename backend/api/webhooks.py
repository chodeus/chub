"""
Webhook processing API endpoints for CHUB.

Provides webhook handling for automated poster processing,
media event notifications, and external service integrations.
"""

import hashlib
import hmac
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.api.utils import (
    BODY_TOO_LARGE,
    body_too_large_error,
    error,
    get_database,
    get_logger,
    ok,
    read_request_json,
)
from backend.util.config import ConfigError, load_config
from backend.util.database import ChubDB
from backend.util.rate_limiter import webhook_limiter
from backend.util.webhook_processor import WebhookProcessor, resolve_client_host
from backend.util.webhook_provisioner import (
    CHUB_NOTIFICATION_NAME,
    deprovision_all,
    normalize_base_url,
    provision_all,
    status_report,
)


def verify_webhook_secret(request: Request) -> None:
    """
    Optionally verify the configured webhook secret on inbound webhook
    requests. Matches Sonarr/Radarr behaviour: if `general.webhook_secret`
    is unset, webhooks are accepted unauthenticated. If it is set, callers
    must send it via `X-Webhook-Secret` header or `?secret=` query param.
    """
    # ConfigError propagates to the shared CONFIG_INVALID handler — these
    # endpoints are secret-gated only, and an unverifiable secret fails closed.
    cfg = load_config()

    expected = (cfg.general.webhook_secret or "").strip()
    if not expected:
        return  # Not configured → no check (local-first default).

    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get(
        "secret", ""
    )
    if not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


# Persistent webhook dedup TTL (seconds). Sonarr/Radarr retry on minute-long
# intervals; the previous in-memory 5s window never caught those and was wiped
# on restart. Backed by the `webhook_cache` table via `db.webhook_cache`.
_WEBHOOK_DEDUP_TTL_SECONDS = 600

# Accepted webhook eventType values, per the authoritative Sonarr/Radarr
# WebhookEventType enums. Both apps emit "Download" for a file import — the UI
# triggers On File Import, On File Upgrade AND On Import Complete all send it
# (OnDownload/OnImportComplete, isUpgrade distinguishes import vs upgrade). The
# pre-download library add is "SeriesAdd" (Sonarr) / "MovieAdded" (Radarr).
# There is NO "EpisodeFileImported"/"MovieFileImported" event — those never
# existed in either enum. `Grab` (no file on disk yet) and lifecycle events
# (Rename, *Delete, Health*, ApplicationUpdate, ManualInteractionRequired) are
# 200-acknowledged but skipped.
_ACCEPTED_EVENT_TYPES = frozenset(
    {
        "Download",  # Sonarr + Radarr — a file was imported (import/upgrade/import-complete)
        "SeriesAdd",  # Sonarr — series added to library (pre-download)
        "MovieAdded",  # Radarr — movie added to library (pre-download)
    }
)

# Import-phase events (a file now exists on disk); the rest of the accepted set
# is the pre-download "added" phase.
_IMPORT_EVENTS = frozenset({"Download"})

router = APIRouter(
    prefix="/api/webhooks",
    tags=["Webhooks"],
    # Rate-limit every webhook route so a misbehaving (or hostile) caller
    # can't flood the job queue. Applied in addition to the optional shared
    # secret in verify_webhook_secret.
    dependencies=[Depends(webhook_limiter)],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Invalid webhook payload"},
        429: {"description": "Rate limit exceeded"},
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

        # Extract client information for logging and debugging. Only the
        # fields actually used downstream (ARR-instance resolution) are kept —
        # the full header map is deliberately NOT stored: it carries the
        # X-Webhook-Secret (and any Authorization/Cookie), which would then be
        # persisted in cleartext in the jobs table, dumped into backups, and
        # echoed back by GET /api/jobs/{id}.
        #
        # Behind a reverse proxy the peer IP is the proxy's, so honor
        # X-Forwarded-For / X-Real-IP when the peer is a configured trusted
        # proxy (general.trusted_proxies) — this recovers the arr's real IP for
        # instance matching. A forged XFF from an untrusted caller is ignored.
        peer_host = request.client.host if request.client else None
        # Unguarded on purpose: this decides whether XFF is honoured, so an
        # indeterminate trust model must reject the webhook, not guess at it.
        trusted_proxies = load_config().general.trusted_proxies
        client_info = {
            "client_host": resolve_client_host(
                peer_host,
                request.headers.get("X-Forwarded-For")
                or request.headers.get("X-Real-IP"),
                trusted_proxies,
            ),
            # Optional explicit instance selector. The reliable way to route a
            # webhook when the peer IP can't identify the sender (reverse proxy,
            # host networking, or several instances sharing an IP): the user
            # adds `?instance=<CHUB instance name>` to the webhook URL or an
            # `X-Chub-Instance` header. Takes precedence over IP auto-matching.
            "instance_override": (
                request.query_params.get("instance")
                or request.headers.get("X-Chub-Instance")
            ),
            "scheme": getattr(request.url, "scheme", "http"),
            "user_agent": request.headers.get("User-Agent", ""),
        }

        # Parse webhook payload
        data = await read_request_json(request)
        if data is BODY_TOO_LARGE:
            return body_too_large_error()
        # An unusable body used to raise into the 500 handler; keep that
        # response — falling through would enqueue an empty webhook job.
        if not isinstance(data, dict) or not data:
            logger.error("Webhook rejected: missing or unparseable JSON body")
            return error(
                "Webhook processing error",
                code="WEBHOOK_PROCESSING_ERROR",
                status_code=500,
            )

        # Check for test events and handle them specially
        if _is_test_event(data):
            logger.info(
                f"Test event received from {client_info['scheme']}://{client_info['client_host']}"
            )
            return ok(
                "Test webhook received successfully",
                {"event_type": "test"},
            )

        # Skip events that don't correspond to a new on-disk file (Grab,
        # *FileDelete, Rename, HealthIssue, etc.). Acknowledge with 200 so
        # Sonarr/Radarr don't mark the connection broken.
        event_type = data.get("eventType", "")
        if event_type and event_type not in _ACCEPTED_EVENT_TYPES:
            logger.debug(f"Ignoring unsupported event type: {event_type}")
            return ok(
                "Event type not supported — webhook ignored",
                {"event_type": event_type, "status": "skipped"},
            )

        # Deduplicate at API layer before enqueuing — persistent rolling
        # window so Sonarr/Radarr retries are coalesced even across restarts.
        dedup_identity = _webhook_dedup_identity(data, client_info)
        if _is_duplicate_webhook(data, db, logger, client_info):
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
            # Roll back the dedup row recorded above so the arr's retry
            # isn't debounced; best-effort — a second DB failure here must
            # not mask the original 500.
            if dedup_identity is not None:
                try:
                    db.webhook_cache.delete(*dedup_identity)
                except Exception:
                    logger.warning(
                        "Failed to roll back webhook dedup row after enqueue failure",
                        exc_info=True,
                    )
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

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Exception in webhook processing: {e}", exc_info=True)
        return error(
            "Webhook processing error",
            code="WEBHOOK_PROCESSING_ERROR",
            status_code=500,
        )


def _webhook_dedup_identity(data: Dict[str, Any], client_info: Dict[str, Any] = None):
    """Build the ``(item_type, item_name)`` dedup identity for a webhook, or
    ``None`` when the payload has no media block.

    The identity hashes media identity + phase + firing instance + season:

    - **phase** (added vs import): a pre-download MovieAdded/SeriesAdd stays
      distinct from the later import for the same media, so it can't debounce it.
    - **instance**: two *arr instances (e.g. Radarr-HD and Radarr-4K) that both
      import the same movie route to different libraries, so they must NOT
      collapse into one job.
    - **season**: Sonarr fires one webhook PER EPISODE, so per-episode webhooks
      for the same season collapse to a single job — but a DIFFERENT season
      imported in the same window keeps its own identity, so its season poster
      isn't wrongly debounced away.
    """
    media_block = data.get("series") or data.get("movie") or {}
    item_type = "series" if "series" in data else "movie" if "movie" in data else ""
    if not item_type:
        return None

    ci = client_info or {}
    instance = (
        ci.get("instance_override")
        or data.get("instanceName")
        or ci.get("client_host")
        or ""
    )
    season = WebhookProcessor._extract_season_number(data)
    phase = "import" if data.get("eventType", "") in _IMPORT_EVENTS else "added"
    hash_fields = {
        "phase": phase,
        "instance": str(instance).strip().lower(),
        "season": "" if season is None else str(season),
        "title": media_block.get("title", ""),
        "year": str(media_block.get("year", "")),
        "tmdb_id": str(media_block.get("tmdbId", "")),
        "tvdb_id": str(media_block.get("tvdbId", "")),
        "imdb_id": str(media_block.get("imdbId", "")),
    }
    item_name = hashlib.sha256(
        json.dumps(hash_fields, sort_keys=True).encode()
    ).hexdigest()[:16]
    return item_type, item_name


def _is_duplicate_webhook(
    data: Dict[str, Any],
    db: ChubDB,
    logger: Any = None,
    client_info: Dict[str, Any] = None,
) -> bool:
    """
    Check if this webhook is a duplicate against the persistent cache.

    Builds the ``(item_type, item_name)`` identity (see
    ``_webhook_dedup_identity``), then asks ``db.webhook_cache.is_duplicate`` —
    which sweeps expired rows, checks for a match within the TTL window, and
    inserts a fresh row when not seen. Restart-safe.
    """
    identity = _webhook_dedup_identity(data, client_info)
    if identity is None:
        return False
    item_type, item_name = identity

    duplicate = db.webhook_cache.is_duplicate(
        item_type=item_type,
        item_name=item_name,
        ttl_seconds=_WEBHOOK_DEDUP_TTL_SECONDS,
    )
    if duplicate and logger:
        logger.debug(
            f"Duplicate webhook debounced (item_type={item_type}, "
            f"item_name={item_name}, ttl={_WEBHOOK_DEDUP_TTL_SECONDS}s)"
        )
    return duplicate


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
    "/wiring",
    summary="Get webhook wiring details",
    description=(
        "Return the path + optional shared secret the UI needs to build "
        "ready-to-paste poster-webhook URLs for Sonarr/Radarr/Tautulli. "
        "Returns the raw secret only when one is configured; this is the "
        "same value already required to call the poster/add endpoint, so "
        "exposing it inside the UI does not widen the threat model."
    ),
    responses={
        200: {
            "description": "Wiring details retrieved",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Webhook wiring retrieved",
                        "data": {
                            "poster_add_path": "/api/webhooks/poster/add",
                            "secret_configured": True,
                            "secret": "your-secret-value",
                        },
                    }
                }
            },
        }
    },
)
def get_webhook_wiring(
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Return the inbound webhook path and secret for the UI's paste-ready URLs."""
    try:
        logger.debug("Serving GET /api/webhooks/wiring")
        # A malformed config must not render as "no secret configured" — that
        # reads to the admin as a working unauthenticated setup.
        secret = (load_config().general.webhook_secret or "").strip()

        resp = ok(
            "Webhook wiring retrieved",
            {
                "poster_add_path": "/api/webhooks/poster/add",
                "secret_configured": bool(secret),
                "secret": secret,
            },
        )
        # This response body carries the raw webhook secret (by design — the UI
        # builds paste-ready ARR URLs from it, and it now sits behind JWT auth).
        # Forbid caching so it never lands in browser/proxy caches.
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Error retrieving webhook wiring: {e}")
        return error(
            "Error retrieving webhook wiring",
            code="WEBHOOK_WIRING_ERROR",
            status_code=500,
        )


def _resolve_provision_base_url(cfg: Any, requested):
    """Resolve the arr-reachable CHUB base URL: the request's ``base_url`` first,
    then the saved ``general.public_url``. Returns ``(normalized, error)``."""
    raw = (requested or "").strip() or (cfg.general.public_url or "").strip()
    return normalize_base_url(raw)


def _normalize_only(value):
    """A request ``instances`` value → the provisioner's ``only`` list, or None
    (= all eligible) for None/empty/["all"]."""
    if (
        isinstance(value, list)
        and value
        and not any(str(v).strip().lower() == "all" for v in value)
    ):
        return [str(v) for v in value]
    return None


@router.get(
    "/provision/status",
    summary="Poster-webhook provisioning status",
    description=(
        "Dry-run reconcile: for each Radarr/Sonarr instance, report whether "
        "CHUB's poster webhook is set up, drifted, missing, or the instance is "
        "unreachable/skipped. Returns booleans/drift-field names only — never the "
        "secret-bearing URL."
    ),
    responses={401: {"description": "Authentication required"}},
)
async def get_provision_status(
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Report per-instance CHUB webhook wiring state (never the secret URL)."""
    try:
        cfg = load_config()
        secret = (cfg.general.webhook_secret or "").strip() or None
        # Resolve the base URL and reconcile in ONE off-loop hop (all arr I/O,
        # incl. auto-detection, runs in the threadpool so the event loop stays
        # free for the arr's save-time test callback). Base-URL precedence:
        # ?base_url= the user typed → saved public_url → a URL auto-detected from
        # an existing arr webhook → the browser origin hint (last resort).
        report = await run_in_threadpool(
            status_report,
            cfg,
            secret,
            explicit=request.query_params.get("base_url"),
            origin_hint=request.query_params.get("origin_hint"),
            logger=logger,
        )
        payload: Dict[str, Any] = {
            "notification_name": CHUB_NOTIFICATION_NAME,
            "public_url_configured": bool((cfg.general.public_url or "").strip()),
            "secret_configured": bool(secret),
            **report,
        }
        resp = ok("Webhook provisioning status", payload)
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ConfigError:
        raise  # shared CONFIG_INVALID contract in main.py
    except Exception as e:
        logger.error(f"Error retrieving provisioning status: {e}", exc_info=True)
        return error(
            "Error retrieving provisioning status",
            code="WEBHOOK_PROVISION_STATUS_ERROR",
            status_code=500,
        )


@router.post(
    "/provision",
    summary="Provision the poster webhook into Radarr/Sonarr",
    description=(
        "Create or update CHUB's poster webhook (Connect entry) in the selected "
        "instances via each arr's own API, with ?instance= (and the secret, if "
        "set) baked into the URL. Idempotent (matched by a fixed notification "
        "name). Body: {instances?: names|['all'], base_url?, include_upgrade?, "
        "force_save?}."
    ),
    responses={
        400: {"description": "Invalid base URL"},
        401: {"description": "Authentication required"},
    },
)
async def provision_webhooks(
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Create or repair the CHUB notification on each selected ARR instance."""
    try:
        cfg = load_config()
        body = await read_request_json(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        # A non-object body used to raise into the 500 handler; keep that
        # response so a truncated body can't read as "provision every instance".
        if not isinstance(body, dict):
            return error(
                "Error provisioning webhooks",
                code="WEBHOOK_PROVISION_ERROR",
                status_code=500,
            )
        base_url, base_err = _resolve_provision_base_url(cfg, body.get("base_url"))
        if base_err:
            return error(base_err, code="WEBHOOK_PROVISION_BASE_URL", status_code=400)
        secret = (cfg.general.webhook_secret or "").strip() or None
        # Off the event loop: the arr runs a save-time test that POSTs back to
        # CHUB, which deadlocks if this blocks the loop (see get_provision_status).
        results = await run_in_threadpool(
            provision_all,
            cfg,
            base_url,
            secret,
            include_upgrade=bool(body.get("include_upgrade")),
            force_save=bool(body.get("force_save")),
            only=_normalize_only(body.get("instances")),
            logger=logger,
        )
        applied = sum(1 for r in results if r.get("action") in ("created", "updated"))
        logger.info(
            f"Webhook provisioning: {applied} written across {len(results)} "
            f"instance(s) at base {base_url}"
        )
        resp = ok(
            "Webhook provisioning complete",
            {"instances": results, "base_url": base_url},
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ConfigError:
        raise  # shared CONFIG_INVALID contract in main.py
    except Exception as e:
        logger.error(f"Error provisioning webhooks: {e}", exc_info=True)
        return error(
            "Error provisioning webhooks",
            code="WEBHOOK_PROVISION_ERROR",
            status_code=500,
        )


@router.post(
    "/provision/remove",
    summary="Remove CHUB's poster webhook from Radarr/Sonarr",
    description=(
        "Delete the CHUB-owned poster webhook (Connect entry) from the selected "
        "instances. Only CHUB's own fixed-name entry is removed; user-made "
        "webhooks are left untouched. Body: {instances?: names|['all']}."
    ),
    responses={401: {"description": "Authentication required"}},
)
async def remove_webhooks(
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Delete the CHUB notification from each selected ARR instance."""
    try:
        cfg = load_config()
        body = await read_request_json(request)
        if body is BODY_TOO_LARGE:
            return body_too_large_error()
        # A non-object body used to raise into the 500 handler; keep that
        # response so a truncated body can't read as "remove from every instance".
        if not isinstance(body, dict):
            return error(
                "Error removing webhooks",
                code="WEBHOOK_REMOVE_ERROR",
                status_code=500,
            )
        results = await run_in_threadpool(
            deprovision_all,
            cfg,
            only=_normalize_only(body.get("instances")),
            logger=logger,
        )
        removed = sum(1 for r in results if r.get("action") == "removed")
        logger.info(
            f"Webhook removal: {removed} deleted across {len(results)} instance(s)"
        )
        resp = ok("Webhook removal complete", {"instances": results})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ConfigError:
        raise  # shared CONFIG_INVALID contract in main.py
    except Exception as e:
        logger.error(f"Error removing webhooks: {e}", exc_info=True)
        return error(
            "Error removing webhooks",
            code="WEBHOOK_REMOVE_ERROR",
            status_code=500,
        )


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
def get_unmatched_webhook_status(
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
            "Error retrieving unmatched status",
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
def process_unmatched_webhook(
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
            "Error processing unmatched webhook",
            code="UNMATCHED_PROCESS_ERROR",
            status_code=500,
        )
