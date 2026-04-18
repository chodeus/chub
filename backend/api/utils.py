# api/utils.py

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
        log_level = getattr(module_config, "log_level", "info") if module_config else "info"
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
