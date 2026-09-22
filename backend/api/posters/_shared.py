"""Shared router dependencies for the poster API modules."""

from typing import Any, List, Optional

from fastapi import APIRouter, Request

from backend.api.utils import get_module_logger
from backend.util.config import load_config
from backend.util.gdrive_source import build_drive_map, resolve_drive_for_path

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


def annotate_drive(rows: Optional[List[dict]], path_key: str = "file") -> None:
    """Stamp each row with `drive`: the configured Google Drive that supplied it.

    Takes a list, not any iterable: it mutates the dicts, and a generator would
    be consumed here leaving the caller nothing. ConfigError propagates, so a
    broken config is reported as one instead of every row reading `drive: null`,
    which is indistinguishable from a path on no configured drive.
    """
    if not rows:
        return
    sync_cfg = getattr(load_config(), "sync_gdrive", None)
    drive_map = build_drive_map(getattr(sync_cfg, "gdrive_list", None))
    for row in rows:
        if isinstance(row, dict):
            row["drive"] = resolve_drive_for_path(row.get(path_key) or "", drive_map)
