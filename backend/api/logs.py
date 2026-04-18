import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from backend.api.utils import error, get_logger, ok
from backend.modules import MODULES

if os.environ.get("DOCKER_ENV"):
    LOG_BASE_DIR = "/config/logs"
else:
    LOG_BASE_DIR = str((Path(__file__).parents[2] / "logs").resolve())

# Allow-list of module names accepted by the log-reading endpoints. Anything
# outside this set is rejected before touching the filesystem, which keeps
# user-controlled path components from reaching os.path.join even indirectly.
# "general" is the shared/root log emitted by the main app (not a module).
VALID_LOG_MODULES = set(MODULES.keys()) | {"general"}

router = APIRouter(
    prefix="/api",
    tags=["Logs"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Log file or module not found"},
        403: {"description": "Access denied"},
    },
)


@router.get("/logs")
async def list_logs(logger: Any = Depends(get_logger)) -> Dict[str, Any]:
    """
    List all available log modules.

    Returns directories in the logs folder that contain module logs.
    """
    try:
        logger.debug(f"Listing log modules in {LOG_BASE_DIR}")

        if not os.path.exists(LOG_BASE_DIR):
            return ok(
                "No logs directory found",
                {"modules": []},
            )

        # Modules with log directories on disk
        disk_modules = set()
        if os.path.exists(LOG_BASE_DIR):
            disk_modules = {
                module
                for module in os.listdir(LOG_BASE_DIR)
                if os.path.isdir(os.path.join(LOG_BASE_DIR, module)) and module != "debug"
            }

        # Union with all known modules so they appear even before first run
        known_modules = set(MODULES.keys()) | {"general"}
        modules = sorted(disk_modules | known_modules)

        logger.debug("Log modules listed: %s", modules)
        return ok(
            f"Found {len(modules)} log modules",
            {"modules": modules},
        )

    except Exception as e:
        logger.error(f"Error listing log modules: {e}")
        return error(
            f"Error listing log modules: {str(e)}",
            code="LOG_MODULES_LIST_ERROR",
            status_code=500,
        )


@router.get("/logs/{module_name}")
async def list_logs_for_module(
    module_name: str, logger: Any = Depends(get_logger)
) -> Dict[str, Any]:
    """
    List all log files for a specific module.

    Returns sorted list of log files in the module's log directory.
    """
    try:
        logger.debug(f"Listing logs for module: {module_name}")

        # Allow-list guard: reject unknown modules before touching the
        # filesystem. Covers path-injection and makes the intent explicit
        # (basename alone is safe, but CodeQL doesn't recognize it as a
        # sanitizer and we'd rather fail closed than lean on implicit trust).
        if module_name not in VALID_LOG_MODULES:
            return error(
                f"Unknown module '{module_name}'",
                code="UNKNOWN_MODULE",
                status_code=404,
            )
        module_path = os.path.join(LOG_BASE_DIR, module_name)

        if not os.path.isdir(module_path):
            # Module hasn't run yet — return empty list instead of 404
            return ok(
                f"No logs yet for module '{module_name}'",
                {"files": []},
            )

        files = sorted(
            f
            for f in os.listdir(module_path)
            if os.path.isfile(os.path.join(module_path, f))
        )

        return ok(
            f"Found {len(files)} log files for module '{module_name}'",
            {"files": files},
        )

    except Exception as e:
        logger.error(f"Error listing logs for module {module_name}: {e}")
        return error(
            f"Error listing module logs: {str(e)}",
            code="MODULE_LOGS_LIST_ERROR",
            status_code=500,
        )


@router.get("/logs/{module}/{filename}", response_class=PlainTextResponse)
async def read_log(
    module: str, filename: str, logger: Any = Depends(get_logger)
) -> PlainTextResponse:
    """
    Read and return the contents of a specific log file.

    Returns the raw log file content as plain text. Security measures prevent
    access to debug logs and directory traversal attacks.
    """
    try:
        # Allow-list the module name (same guard as list_logs_for_module).
        # Filename still goes through basename+realpath because it's
        # user-driven but constrained to a known module dir.
        if module not in VALID_LOG_MODULES:
            return error(
                "Log file not found",
                code="LOG_FILE_NOT_FOUND",
                status_code=404,
            )
        safe_filename = os.path.basename(filename)

        log_path = os.path.join(LOG_BASE_DIR, module, safe_filename)

        # Additional security check for debug logs in path
        if "debug" in os.path.relpath(log_path, LOG_BASE_DIR).split(os.sep):
            return error(
                "Log file not found",
                code="LOG_FILE_NOT_FOUND",
                status_code=404,
            )

        if not os.path.exists(log_path):
            return error(
                "Log file not found",
                code="LOG_FILE_NOT_FOUND",
                status_code=404,
            )

        # Verify the file is within our allowed directory
        resolved_path = os.path.realpath(log_path)
        resolved_base = os.path.realpath(LOG_BASE_DIR)
        if not resolved_path.startswith(resolved_base + os.sep) and resolved_path != resolved_base:
            return error(
                "Access denied",
                code="LOG_ACCESS_DENIED",
                status_code=403,
            )

        with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        return PlainTextResponse(content)

    except PermissionError:
        logger.error(f"Permission denied accessing log file: {module}/{filename}")
        return error(
            "Permission denied accessing log file",
            code="LOG_PERMISSION_DENIED",
            status_code=403,
        )
    except Exception as e:
        logger.error(f"Error reading log file {module}/{filename}: {e}")
        return error(
            f"Error reading log file: {str(e)}",
            code="LOG_READ_ERROR",
            status_code=500,
        )
