import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
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
    config as config_router,
    instances as instances_router,
    jobs as jobs_router,
    labelarr as labelarr_router,
    logs as logs_router,
    media as media_router,
    media_api as media_api_router,
    modules as modules_router,
    nestarr as nestarr_router,
    notifications as notifications_router,
    posters as posters_router,
    schedule as schedule_router,
    system as system_router,
    webhooks as webhooks_router,
)
from backend.api.utils import error, get_logger
from backend.util.auth import decode_access_token
from backend.util.config import ConfigError, load_config
from backend.util.database import ChubDB
from backend.util.job_processor import process_job


# Paths that do NOT require authentication
AUTH_EXEMPT_PREFIXES = (
    "/api/auth/",
    "/api/health",
    "/api/version",
    "/assets/",
    "/icons/",
    "/img/",
    "/posters/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Require a valid JWT Bearer token on all /api/* routes
    (except auth, health, version, and static assets).
    When auth is not yet configured, all requests are allowed
    so the setup flow can proceed.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Non-API and exempt paths pass through
        if not path.startswith("/api/") or path.startswith(AUTH_EXEMPT_PREFIXES):
            return await call_next(request)

        # Check if auth is configured
        try:
            config = load_config()
        except ConfigError:
            # If config can't be loaded, let the request through —
            # downstream handlers will return their own errors.
            return await call_next(request)

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
            return JSONResponse(
                status_code=401,
                content={
                    "success": False,
                    "message": "Invalid or expired token",
                    "error_code": "AUTH_TOKEN_INVALID",
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

# Frontend static directory — configurable via STATIC_DIR env var.
# Defaults to templates/ (local dev); Docker sets STATIC_DIR=/app/public.
STATIC_DIR = Path(
    os.environ.get("STATIC_DIR", str(Path(__file__).parents[2] / "templates"))
)

app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
app.mount("/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons")
app.mount("/img", StaticFiles(directory=STATIC_DIR / "img"), name="img")
app.mount("/posters", StaticFiles(directory=STATIC_DIR / "posters"), name="posters")


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler with standardized payload."""
    logger = get_logger(request, "ERROR")
    logger.error(f"Unhandled Exception: {exc}", exc_info=True)
    return error(
        f"Internal server error: {str(exc)}", code="INTERNAL_ERROR", status_code=500
    )


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
app.include_router(system_router.router)
app.include_router(config_router.router)
app.include_router(instances_router.router)
app.include_router(schedule_router.router)
app.include_router(jobs_router.router)
app.include_router(modules_router.router)
app.include_router(logs_router.router)
app.include_router(media_router.router)
app.include_router(media_api_router.router)
app.include_router(posters_router.router)
app.include_router(webhooks_router.router)
app.include_router(nestarr_router.router)
app.include_router(notifications_router.router)
app.include_router(labelarr_router.router)
app.include_router(router)


# Generic endpoints moved to system.py router


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serves the main index.html page."""
    html_path = STATIC_DIR / "index.html"
    try:
        return HTMLResponse(content=html_path.read_text(), status_code=200)
    except Exception as e:
        return error(
            f"Error serving index page: {str(e)}",
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
