import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from backend.api.utils import error, get_logger, ok
from backend.extensions import extension_config_fields
from backend.modules import MODULES
from backend.util.paths import get_log_base_dir


def _log_base_dir() -> str:
    """Read per request, so it always matches where the logger writes."""
    return str(Path(get_log_base_dir()).resolve())


# A view's first read; above the 10 MB default rotation size, so a normal log loads whole.
VIEW_CAP = 16 * 1024 * 1024


def _log_id(f: Any, st: os.stat_result) -> str:
    """Inode plus a hash of the first line, which starts with its timestamp: a new log on a reused inode differs unless that line matches."""
    f.seek(0)
    first = f.read(512).partition(b"\n")[0]
    return f"{st.st_ino}:{hashlib.sha256(first).hexdigest()[:12]}"


def _view(path: str, offset: int, log_id: str, view_start: int) -> PlainTextResponse:
    """Whole lines after ``offset``, or the last VIEW_CAP bytes when the client must start over."""
    with open(path, "rb") as f:
        st = os.fstat(f.fileno())
        size = st.st_size
        cur_id = _log_id(f, st)
        # Past twice the cap, so a view stays bounded without re-sending it on every poll.
        reset = (
            offset == 0
            or log_id != cur_id
            or offset > size
            or size - view_start > 2 * VIEW_CAP
        )
        start = offset
        if reset:
            start = max(0, size - VIEW_CAP)
            if start:
                f.seek(start - 1)
                f.readline()
                start = f.tell()
            view_start = start
        f.seek(start)
        data = f.read(max(0, size - start))
    # A line still being written waits for its newline; a newline is never inside a UTF-8 sequence.
    data = data[: data.rfind(b"\n") + 1]
    return PlainTextResponse(
        data.decode("utf-8", errors="replace"),
        headers={
            "X-Log-Id": cur_id,
            "X-Log-Offset": str(start + len(data)),
            "X-Log-Start": str(view_start),
            "X-Log-Reset": "1" if reset else "0",
        },
    )


# Allow-list of module names accepted by the log-reading endpoints. Anything
# outside this set is rejected before touching the filesystem, which keeps
# user-controlled path components from reaching os.path.join even indirectly.
# "general" is the shared/root log emitted by the main app (not a module).
# extension_config_fields() adds CONFIG-ONLY extension modules (e.g. cl2k_maker)
# that log via get_module_logger but aren't in the runnable MODULES registry —
# empty on main. Computed per call so late extension registration is reflected.
def _valid_log_modules() -> set:
    return set(MODULES.keys()) | {"general"} | set(extension_config_fields().keys())


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
def list_logs(logger: Any = Depends(get_logger)) -> Dict[str, Any]:
    """
    List all available log modules.

    Returns directories in the logs folder that contain module logs.
    """
    try:
        logger.debug(f"Listing log modules in {_log_base_dir()}")

        if not os.path.exists(_log_base_dir()):
            return ok(
                "No logs directory found",
                {"modules": []},
            )

        # List every known module (so they appear even before first run). We
        # intentionally do NOT surface arbitrary on-disk dirs: list_logs_for_module
        # only serves VALID_LOG_MODULES, so a stale/unknown dir left by an older
        # build (e.g. an 'orphan-dryrun' leftover) would otherwise show as a dead
        # entry that 404s when opened.
        modules = sorted(_valid_log_modules())

        logger.debug("Log modules listed: %s", modules)
        return ok(
            f"Found {len(modules)} log modules",
            {"modules": modules},
        )

    except Exception as e:
        logger.error(f"Error listing log modules: {e}")
        return error(
            "Error listing log modules",
            code="LOG_MODULES_LIST_ERROR",
            status_code=500,
        )


@router.get("/logs/{module_name}")
def list_logs_for_module(
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
        if module_name not in _valid_log_modules():
            return error(
                f"Unknown module '{module_name}'",
                code="UNKNOWN_MODULE",
                status_code=404,
            )
        module_path = os.path.join(_log_base_dir(), module_name)

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
            "Error listing module logs",
            code="MODULE_LOGS_LIST_ERROR",
            status_code=500,
        )


@router.get("/logs/{module}/{filename}", response_class=PlainTextResponse)
def read_log(
    module: str,
    filename: str,
    offset: Optional[int] = Query(
        None, ge=0, description="View mode: the X-Log-Offset of the last read; 0 starts over."
    ),
    log_id: str = Query(
        "", alias="id", max_length=64, description="View mode: the X-Log-Id of the last read."
    ),
    view_start: int = Query(
        0, alias="start", ge=0, description="View mode: the X-Log-Start of the last read."
    ),
    logger: Any = Depends(get_logger),
) -> PlainTextResponse:
    """Return a log as plain text: the whole file, or with ``offset`` one ``_view`` read (X-Log-* headers)."""
    try:
        # Allow-list the module name (same guard as list_logs_for_module).
        # Filename still goes through basename+realpath because it's
        # user-driven but constrained to a known module dir.
        if module not in _valid_log_modules():
            return error(
                "Log file not found",
                code="LOG_FILE_NOT_FOUND",
                status_code=404,
            )
        safe_filename = os.path.basename(filename)

        log_path = os.path.join(_log_base_dir(), module, safe_filename)

        # Additional security check for debug logs in path
        if "debug" in os.path.relpath(log_path, _log_base_dir()).split(os.sep):
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
        resolved_base = os.path.realpath(_log_base_dir())
        if (
            not resolved_path.startswith(resolved_base + os.sep)
            and resolved_path != resolved_base
        ):
            return error(
                "Access denied",
                code="LOG_ACCESS_DENIED",
                status_code=403,
            )

        if offset is not None:
            return _view(resolved_path, offset, log_id, view_start)

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
            "Error reading log file",
            code="LOG_READ_ERROR",
            status_code=500,
        )
