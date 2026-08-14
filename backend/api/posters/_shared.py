"""Shared router dependencies for the poster API modules."""

from typing import Any

from fastapi import APIRouter, Request

from backend.api.utils import get_module_logger

router = APIRouter(
    prefix="/api/posters",
    tags=["Posters"],
    responses={
        500: {"description": "Internal server error"},
        404: {"description": "Poster or resource not found"},
    },
)


def get_cleanarr_logger(request: Request) -> Any:
    """FastAPI dependency: module-dedicated logger for `/plex-metadata/*` calls.

    Routes UI-triggered scans, deletes, and set-active into
    `logs/poster_cleanarr/poster_cleanarr.log` so every user action the
    Poster Cleanarr page takes leaves an audit trail in the module's log —
    not just scheduled module runs.
    """
    return get_module_logger(request, "poster_cleanarr")
