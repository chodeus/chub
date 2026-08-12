"""First-run setup-wizard status endpoints for CHUB.

The wizard is gated on ``general.setup_completed``. A fresh install starts False
and the frontend routes into the wizard; existing installs are backfilled True by
``load_config`` so they never see it. These endpoints let the frontend read that
flag and mark setup done when the wizard finishes.
"""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.api.utils import error, get_logger, ok
from backend.util.config import ConfigError, load_config, save_config

router = APIRouter(
    prefix="/api/setup",
    tags=["Setup"],
)


def _is_setup_completed() -> bool:
    """Whether the first-run wizard has been completed (or backfilled)."""
    try:
        return bool(load_config().general.setup_completed)
    except ConfigError:
        return False


@router.get(
    "/status",
    summary="Setup status",
    description="Whether the first-run setup wizard has been completed.",
)
async def setup_status(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Return the setup-completed flag. Used by the frontend to decide whether
    to route a first-run install into the wizard."""
    return ok("Setup status retrieved", {"completed": _is_setup_completed()})


@router.post(
    "/complete",
    summary="Mark setup complete",
    description="Flip general.setup_completed True so the wizard no longer shows.",
)
async def complete_setup(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Persist setup completion. Idempotent — safe to call again."""
    try:
        config = load_config()
        config.general.setup_completed = True
        save_config(config)
    except ConfigError as exc:
        logger.error(f"Failed to save setup status: {exc}")
        return error("Failed to save setup status", status_code=500)
    return ok("Setup marked complete", {"completed": True})
