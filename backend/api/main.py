import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api import (
    auth as auth_router,
    border_replacerr as border_replacerr_router,
    cache as cache_router,
    config as config_router,
    instances as instances_router,
    jobs as jobs_router,
    labelarr as labelarr_router,
    logs as logs_router,
    media_api as media_api_router,
    modules as modules_router,
    nestarr as nestarr_router,
    notifications as notifications_router,
    posters as posters_router,
    schedule as schedule_router,
    setup as setup_router,
    system as system_router,
    webhooks as webhooks_router,
)
from backend.api.utils import error, get_logger
from backend.extensions import extension_routers, extension_stream_prefixes
from backend.util.auth import decode_access_token
from backend.util.config import (
    ConfigError,
    ConfigValidationError,
    format_validation_errors,
    format_validation_errors_public,
    load_config,
)
from backend.util.database import ChubDB
from backend.util.helper import get_static_dir
from backend.util.job_processor import process_job
from backend.util.notification import install_error_notify_handler


# Paths that do NOT require authentication
AUTH_EXEMPT_PATHS = (
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/status",
    # Setup status carries no secret and the wizard must be reachable before a
    # login exists, so mirror /api/auth/status and keep it exempt.
    "/api/setup/status",
    # Inbound webhooks from Sonarr/Radarr/Tautulli authenticate with the
    # shared X-Webhook-Secret (verify_webhook_secret), never a JWT. Without
    # this exemption AuthMiddleware would 401 every inbound webhook the moment
    # a login is configured, silently breaking automated processing. Only the
    # secret-gated INGEST endpoints are exempt — the /wiring and
    # /unmatched/status UI endpoints stay behind JWT auth.
    "/api/webhooks/poster/add",
    "/api/webhooks/unmatched/process",
)
AUTH_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/version",
    "/assets/",
    "/icons/",
    "/img/",
    "/posters/",
)

# Routes a scope="stream" token may reach (GET only): image/preview/SSE endpoints
# whose URLs carry the token because <img>/EventSource can't send an auth header.
STREAM_PATH_PREFIXES = (
    "/api/media/",
    "/api/posters/",
    "/api/border-replacerr/preview/",
    "/api/modules/events",
)


# Stamped here AND in handle_exception — Starlette runs an `Exception` handler
# outside the middleware stack. Keep both sites in step.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _stamp_security_headers(response) -> None:
    """Add the baseline headers, never overriding one a route already set."""
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp baseline security headers on every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        _stamp_security_headers(response)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Require a valid JWT Bearer token on all /api/* routes
    (except auth, health, version, and static assets).
    When auth is not yet configured, all requests are allowed
    so the setup flow can proceed.
    """

    @staticmethod
    def _log_unauthorized(request: Request, reason: str, path: str) -> None:
        """Warn (with the request path) on a rejected API call so 401s are
        diagnosable in the logs. Best-effort: a logging failure must never
        affect the auth response itself."""
        try:
            logger = getattr(request.app.state, "logger", None)
            if logger is not None:
                logger.get_adapter("API").warning(
                    f"Unauthorized API request – {reason} ({path})"
                )
        except Exception:
            pass

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Non-API and exempt paths pass through
        if (
            not path.startswith("/api/")
            or path in AUTH_EXEMPT_PATHS
            or path.startswith(AUTH_EXEMPT_PREFIXES)
        ):
            return await call_next(request)

        # Check if auth is configured
        try:
            config = load_config()
        except ConfigError:
            # Auth state is indeterminate when config can't load — fail CLOSED,
            # not open. Exempt paths (health/setup/static) already returned above.
            self._log_unauthorized(request, "config unavailable", path)
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "message": "Configuration unavailable",
                    "error_code": "CONFIG_UNAVAILABLE",
                },
            )

        if not config.auth.username or not config.auth.password_hash:
            # Auth not set up yet — allow all requests (first-run state)
            return await call_next(request)

        # Auth is configured — validate Bearer token.
        # Support both header-based auth (normal API calls) and query-param
        # auth (?token=...) for EventSource/SSE which cannot send headers.
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # strip "Bearer "
        else:
            token = request.query_params.get("token", "")

        if not token:
            self._log_unauthorized(request, "missing Bearer token", path)
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Authentication required",
                    "error_code": "AUTH_REQUIRED",
                },
            )
        payload = decode_access_token(token, config.auth.jwt_secret)
        if payload is None:
            self._log_unauthorized(request, "invalid or expired token", path)
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Invalid or expired token",
                    "error_code": "AUTH_TOKEN_INVALID",
                },
            )

        # A scope-limited stream token (URL-embedded auth for images/SSE) is only
        # valid for GET requests on the stream allowlist — never for mutations or
        # general API access, so a leaked image/SSE URL can't do more than that.
        if payload.get("scope") == "stream" and (
            request.method != "GET"
            or not path.startswith(STREAM_PATH_PREFIXES + extension_stream_prefixes())
        ):
            self._log_unauthorized(request, "stream token off stream route", path)
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "message": "Token not valid for this route",
                    "error_code": "AUTH_SCOPE_INVALID",
                },
            )

        # Attach user info to request state for downstream use
        request.state.user = payload.get("sub", "")
        return await call_next(request)


# Version functionality now in system.py


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager with proper startup/shutdown"""

    logger = app.state.logger
    log = logger.get_adapter("FASTAPI") if logger else None

    try:
        if log:
            log.debug("Starting FastAPI application...")

        app.state.started_at = time.time()

        try:
            startup_config = load_config()
            # The webhook ingest endpoints are auth-exempt and gated only by the
            # optional shared secret. If it's unset they accept unauthenticated
            # POSTs — fine on a trusted LAN, but a reverse-proxied / internet-
            # exposed instance would take job-injection from anyone. Warn loudly.
            if (
                log
                and not (
                    getattr(startup_config.general, "webhook_secret", "") or ""
                ).strip()
            ):
                log.warning(
                    "SECURITY: webhook ingest endpoints (/api/webhooks/poster/add, "
                    "/api/webhooks/unmatched/process) are UNAUTHENTICATED — no "
                    "general.webhook_secret is set. Safe on a trusted LAN, but if "
                    "CHUB is behind a reverse proxy or otherwise reachable off-LAN, "
                    "set a webhook_secret and add it to your *arr webhook URLs."
                )
            # Only nag installs that actually sync — an empty gdrive_list never
            # invokes rclone, so the shared client can't bite them.
            sync_cfg = getattr(startup_config, "sync_gdrive", None)
            if log and sync_cfg and getattr(sync_cfg, "gdrive_list", None):
                from backend.modules.sync_gdrive import uses_shared_rclone_client_id

                if uses_shared_rclone_client_id(sync_cfg):
                    log.warning(
                        "GDrive sync is using rclone's shared Google Drive client_id, "
                        "which rclone is RETIRING during 2026 — syncs will stop "
                        "working. It also shares one 10 requests/sec Google quota "
                        "with every other rclone user. Set sync_gdrive."
                        "gdrive_sa_location to a service-account keyfile "
                        "(recommended), or your own sync_gdrive.client_id / "
                        "client_secret / token."
                    )
            handler = install_error_notify_handler(startup_config, logger=logger)
            if handler and log:
                log.debug(
                    "ErrorNotifyHandler attached to root logger — ERROR-level logs "
                    "will be forwarded to notification destinations with the "
                    "'On failure' trigger enabled."
                )
        except ConfigError as exc:
            if log:
                log.error(f"Configuration could not be loaded: {exc}")
                if isinstance(exc, ConfigValidationError) and exc.validation_error:
                    for line in format_validation_errors(exc.validation_error):
                        log.error(f"  • {line}")
                log.debug("Skipped ErrorNotifyHandler setup — config not loadable yet.")

        # CREATE SHARED DATABASE INSTANCE FOR ALL API ENDPOINTS
        try:
            app.state.db = ChubDB(
                logger=logger, quiet=False
            )  # Temporarily remove quiet for debugging
            app.state.db.__enter__()  # Initialize the context manually

            # UPDATE MODULE ORCHESTRATOR TO USE SHARED DATABASE
            if (
                hasattr(app.state, "module_orchestrator")
                and app.state.module_orchestrator
            ):
                app.state.module_orchestrator.db = app.state.db
        except Exception as e:
            if log:
                log.error(f"Failed to create shared database: {e}")
            raise

        if log:
            log.debug("Creating database workers...")

        # Use the shared database instance for workers
        app.state.webhook_worker = app.state.db.create_worker(
            logger=logger,
            num_workers=2,
            worker_name="WEBHOOK",
            job_type_filter="webhook",
        )

        app.state.background_worker = app.state.db.create_worker(
            logger=logger,
            num_workers=3,
            worker_name="BACKGROUND",
            job_type_filter=None,
        )

        if log:
            log.debug("Starting database workers...")

        # Create wrapper function that passes shared database context
        def shared_db_process_job(job, logger):
            """Wrapper that passes shared database context to process_job"""
            return process_job(job, logger, app.state.db)

        # FIXED: Use wrapper function that passes shared database context
        app.state.webhook_worker.start(
            table_name="jobs",
            process_fn=shared_db_process_job,
            job_type_filter="webhook",
        )

        app.state.background_worker.start(
            table_name="jobs", process_fn=shared_db_process_job, job_type_filter=None
        )

        # Daily maintenance: auto config backups + log pruning (both gated on
        # config; the thread is a cheap no-op when disabled).
        try:
            if "startup_config" in locals() and startup_config is not None:
                from backend.util.maintenance import start_maintenance

                app.state.maintenance_thread = start_maintenance(logger)
        except Exception as e:
            if log:
                log.error(f"Failed to start maintenance thread: {e}")

        if log:
            log.info("FastAPI application started successfully")

        yield

    except Exception as e:
        if log:
            log.error(f"Error during FastAPI startup: {e}", exc_info=True)
        else:
            print(f"[FASTAPI] Startup error: {e}")
        raise

    finally:
        if log:
            log.debug("Shutting down FastAPI application...")
        else:
            print("[FASTAPI] Shutting down...")

        try:
            # SIMPLIFIED: Cleaner shutdown
            workers_to_stop = []
            if hasattr(app.state, "webhook_worker") and app.state.webhook_worker:
                workers_to_stop.append(("webhook_worker", app.state.webhook_worker))
            if hasattr(app.state, "background_worker") and app.state.background_worker:
                workers_to_stop.append(
                    ("background_worker", app.state.background_worker)
                )

            def stop_worker_with_timeout(
                name: str, worker: Any, timeout: int = 8
            ) -> None:
                try:
                    if log:
                        log.debug(f"Stopping {name}...")
                    worker.stop(timeout=timeout)
                    if log:
                        log.debug(f"{name} stopped successfully")
                except Exception as e:
                    if log:
                        log.error(f"Error stopping {name}: {e}")

            # Stop workers in parallel
            stop_threads = []
            for name, worker in workers_to_stop:
                thread = threading.Thread(
                    target=stop_worker_with_timeout, args=(name, worker, 8), daemon=True
                )
                thread.start()
                stop_threads.append(thread)

            # Wait for all to finish
            for thread in stop_threads:
                thread.join(timeout=10)

            # CLEANUP SHARED DATABASE
            if hasattr(app.state, "db") and app.state.db:
                try:
                    app.state.db.__exit__(None, None, None)  # Cleanup manually
                    if log:
                        log.debug("Shared database closed successfully")
                except Exception as e:
                    if log:
                        log.error(f"Error closing shared database: {e}")

            if log:
                log.info("FastAPI application shutdown complete")

        except Exception as e:
            if log:
                log.error(f"Error during FastAPI shutdown: {e}", exc_info=True)


app = FastAPI(
    title="CHUB API",
    description="Dynamic Asset and Poster System - Media automation and poster management API",
    version="3.0.0-alpha",
    lifespan=lifespan,
    tags_metadata=[
        {"name": "System", "description": "System-level operations and utilities"},
        {
            "name": "Configuration",
            "description": "Application configuration management",
        },
        {
            "name": "Service Instances",
            "description": "Plex, Radarr, and Sonarr instance management",
        },
        {
            "name": "Schedule Management",
            "description": "Module scheduling configuration",
        },
        {"name": "Jobs", "description": "Background job queue management"},
        {"name": "Modules", "description": "Module execution and orchestration"},
        {"name": "Logs", "description": "Log file access and management"},
        {"name": "Media Cache", "description": "Media cache operations and management"},
        {"name": "Posters", "description": "Poster management and statistics"},
        {"name": "Webhooks", "description": "Webhook processing and automation"},
        {"name": "Notifications", "description": "Notification testing and management"},
        {"name": "Labelarr", "description": "Tag synchronization between ARR and Plex"},
    ],
)
router = APIRouter()

# Authentication middleware — must be added before routes
app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Frontend static directory — configurable via STATIC_DIR env var.
# Defaults to templates/ (local dev); Docker sets STATIC_DIR=/app/public.
STATIC_DIR = get_static_dir()

app.mount(
    "/assets",
    StaticFiles(directory=STATIC_DIR / "assets", check_dir=False),
    name="assets",
)
app.mount(
    "/icons", StaticFiles(directory=STATIC_DIR / "icons", check_dir=False), name="icons"
)
app.mount(
    "/img", StaticFiles(directory=STATIC_DIR / "img", check_dir=False), name="img"
)
app.mount(
    "/posters",
    StaticFiles(directory=STATIC_DIR / "posters", check_dir=False),
    name="posters",
)


@app.exception_handler(ConfigError)
async def handle_config_error(request: Request, exc: ConfigError) -> JSONResponse:
    """Surface config load/validation failures clearly instead of as a generic 500.

    Covers ConfigParseError (bad YAML — message carries the file + line) and
    ConfigValidationError (schema mismatch — per-field detail is formatted into
    both the log and the response so a malformed/ported config is diagnosable
    from the logs rather than appearing as an opaque internal error.
    """
    logger = get_logger(request, "ERROR")
    # exc_info carries the __cause__ the curated message deliberately omits
    logger.error(f"Configuration error: {exc}", exc_info=True)
    public_lines = []
    if isinstance(exc, ConfigValidationError) and exc.validation_error:
        # The logged lines carry the offending values; the returned ones must not.
        for line in format_validation_errors(exc.validation_error):
            logger.error(f"  • {line}")
        public_lines = format_validation_errors_public(exc.validation_error)
    return error(
        # Read the curated attribute, never the exception object itself
        "Configuration invalid: " + exc.message,
        code="CONFIG_INVALID",
        data={"errors": public_lines} if public_lines else None,
        status_code=500,
    )


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler with standardized payload."""
    logger = get_logger(request, "ERROR")
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    response = error("Internal server error", code="INTERNAL_ERROR", status_code=500)
    # ServerErrorMiddleware owns this path, outside SecurityHeadersMiddleware.
    _stamp_security_headers(response)
    return response


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Standardize HTTPException responses into the common error envelope."""
    logger = get_logger(request, "ERROR")
    logger.warning(f"HTTP {exc.status_code}: {exc.detail}")

    detail = exc.detail
    if isinstance(detail, dict):
        msg = detail.get("message") or str(detail)
        code = detail.get("error_code") or "HTTP_ERROR"
        data = detail.get("data")
    else:
        msg = str(detail)
        code = "HTTP_ERROR"
        data = None

    return error(msg, code=code, data=data, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def handle_validation_exception(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return a normalized 422 for validation errors."""
    logger = get_logger(request, "ERROR")
    logger.warning(f"Validation error: {exc.errors()}")
    return error(
        "Validation error", code="VALIDATION_ERROR", data=exc.errors(), status_code=422
    )


# Register API routers with proper organization
app.include_router(auth_router.router)
app.include_router(setup_router.router)
app.include_router(system_router.router)
app.include_router(config_router.router)
app.include_router(instances_router.router)
app.include_router(schedule_router.router)
app.include_router(jobs_router.router)
app.include_router(modules_router.router)
app.include_router(logs_router.router)
app.include_router(cache_router.router)
app.include_router(media_api_router.router)
app.include_router(posters_router.router)
app.include_router(webhooks_router.router)
app.include_router(nestarr_router.router)
app.include_router(notifications_router.router)
app.include_router(labelarr_router.router)
app.include_router(border_replacerr_router.router)
for _extension_router in extension_routers():
    app.include_router(_extension_router)
app.include_router(router)


# Generic endpoints moved to system.py router


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """Serves the main index.html page."""
    html_path = STATIC_DIR / "index.html"
    try:
        return HTMLResponse(content=html_path.read_text(), status_code=200)
    except Exception as e:
        get_logger(request, "ERROR").error(f"Error serving index page: {e}")
        return error(
            "Error serving index page",
            code="INDEX_PAGE_ERROR",
            status_code=500,
        )


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def serve_spa(full_path: str) -> FileResponse:
    """Serve index.html for all non-API, non-assets routes (for SPA)"""
    # Exclude API and static asset paths
    if (
        full_path.startswith("api/")
        or full_path == "api"
        or full_path.startswith("assets/")
        or full_path.startswith("icons/")
        or full_path.startswith("img/")
        or full_path.startswith("posters/")
    ):
        raise HTTPException(status_code=404, detail="Resource not found")

    return FileResponse(STATIC_DIR / "index.html")
