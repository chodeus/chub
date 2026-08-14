# api/utils.py

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.util.database import ChubDB
from backend.util.logger import Logger


# Cache module loggers so we don't create duplicates
_module_loggers: dict[str, Logger] = {}


def get_logger(request: Request, source: str = "WEB") -> Any:
    return request.app.state.logger.get_adapter(source)


def _apply_log_settings(module_logger: Logger, log_level: str, max_logs: int) -> None:
    """Push live log_level/max_logs onto a built logger, keeping its file handle."""
    # Attribute access delegates to the underlying stdlib logger (Logger.__getattr__).
    module_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    for handler in module_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.backupCount = max(1, max_logs)


def get_module_logger(request: Request, module_name: str) -> Any:
    """
    Get or create a dedicated file-based logger for a specific module.

    Unlike get_logger() which writes to the general log, this creates
    a separate log file under logs/<module_name>/<module_name>.log so
    each module has its own section in the Logs page.

    Config is re-read per call so a log_level/max_logs change reaches the
    next request instead of being frozen at first use.
    """
    from backend.util.config import load_config

    config = load_config()
    module_config = getattr(config, module_name, None)
    log_level = getattr(module_config, "log_level", "info") if module_config else "info"
    max_logs = config.general.max_logs

    module_logger = _module_loggers.get(module_name)
    if module_logger is None:
        module_logger = Logger(
            log_level=log_level,
            module_name=module_name,
            max_logs=max_logs,
        )
        _module_loggers[module_name] = module_logger
    _apply_log_settings(module_logger, log_level, max_logs)
    return module_logger.get_adapter(module_name.upper())


def get_database(request: Request) -> ChubDB:
    """
    Dependency injection for shared database instance.
    Returns the same database context for all API calls.
    """
    # Temporary debug logging
    logger = request.app.state.logger.get_adapter("DB_INJECTION")

    if not hasattr(request.app.state, "db"):
        logger.error("No shared database found in app.state!")
        raise RuntimeError("Database not available in app state")

    return request.app.state.db


def ok(
    message: str, data: Optional[Any] = None, status_code: int = 200
) -> JSONResponse:
    """Standard success response factory."""
    payload = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return JSONResponse(status_code=status_code, content=payload)


def error(
    message: str,
    code: str = "UNKNOWN_ERROR",
    *,
    data: Optional[Any] = None,
    status_code: int = 400,
) -> JSONResponse:
    """Standard error response factory."""
    payload = {"success": False, "message": message, "error_code": code}
    if data is not None:
        payload["data"] = data
    return JSONResponse(status_code=status_code, content=payload)


def worker_error(
    result: Any, logger: Any, message: str, code: str, status_code: int = 500
) -> Optional[JSONResponse]:
    """Stable response for a failed worker envelope (detail to the log), else None."""
    # Worker messages embed raw exception text, so they never reach the client.
    if not isinstance(result, dict) or result.get("success"):
        return None
    logger.error(f"{message}: {result.get('message')}")
    return error(message, code=code, status_code=status_code)


MAX_REQUEST_BODY_BYTES = 1024 * 1024

# Sentinel outcome, distinct from None (unparseable) and {} (no body).
BODY_TOO_LARGE = object()


async def read_request_json(
    request: Request, max_bytes: int = MAX_REQUEST_BODY_BYTES
) -> Any:
    """Parsed JSON body; {} when empty, None when unparseable, BODY_TOO_LARGE past the cap."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return BODY_TOO_LARGE

    # Chunked bodies carry no Content-Length, so the cap is re-checked per chunk
    # rather than trusting the header — nothing is buffered past the limit.
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            return BODY_TOO_LARGE
        chunks.append(chunk)

    body = b"".join(chunks)
    # Whitespace-only counts as no body — a stray newline shouldn't be a 400.
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except ValueError:
        return None


async def read_json_object(
    request: Request, max_bytes: int = MAX_REQUEST_BODY_BYTES
) -> Any:
    """read_request_json for routes that want an object: any non-object body reads as {}."""
    payload = await read_request_json(request, max_bytes)
    if payload is BODY_TOO_LARGE:
        return payload
    return payload if isinstance(payload, dict) else {}


def body_too_large_error() -> JSONResponse:
    """The single 413 response for a body past the cap."""
    return error("Request body too large", code="BODY_TOO_LARGE", status_code=413)


CACHE_REFRESH_LIST_FIELDS = ("arr_instances", "plex_instances", "libraries")


def build_cache_refresh_payload(payload: Any) -> Optional[dict]:
    """Validated cache_refresh job payload, or None if the body is the wrong shape."""
    # Unknown keys are dropped by construction, so the frontend's {path, deep}
    # body still yields three empty lists — which the worker reads as "refresh all".
    if not isinstance(payload, dict):
        return None
    job_payload = {}
    for field in CACHE_REFRESH_LIST_FIELDS:
        value = payload.get(field, [])
        if not isinstance(value, list):
            return None
        # Names are stripped here; anything beyond "non-empty string" is the
        # worker's and config layer's call, not this validator's.
        names = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return None
            names.append(item.strip())
        job_payload[field] = names
    return job_payload
