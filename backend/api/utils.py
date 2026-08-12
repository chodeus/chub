# api/utils.py

import json
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.util.database import ChubDB
from backend.util.logger import Logger


# Cache module loggers so we don't create duplicates
_module_loggers: dict[str, Logger] = {}


def get_logger(request: Request, source: str = "WEB") -> Any:
    return request.app.state.logger.get_adapter(source)


def get_module_logger(request: Request, module_name: str) -> Any:
    """
    Get or create a dedicated file-based logger for a specific module.

    Unlike get_logger() which writes to the general log, this creates
    a separate log file under logs/<module_name>/<module_name>.log so
    each module has its own section in the Logs page.
    """
    if module_name not in _module_loggers:
        from backend.util.config import load_config

        config = load_config()
        module_config = getattr(config, module_name, None)
        log_level = (
            getattr(module_config, "log_level", "info") if module_config else "info"
        )
        _module_loggers[module_name] = Logger(
            log_level=log_level,
            module_name=module_name,
            max_logs=config.general.max_logs,
        )
    return _module_loggers[module_name].get_adapter(module_name.upper())


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
