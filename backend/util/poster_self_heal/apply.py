# backend/util/poster_self_heal/apply.py
"""Apply a poster_heal_review proposal — rename the poster on the user's Google
Drive and on the local source copy. Shared by the review API (manual apply) and
the module (auto-apply)."""

import os
from typing import Any, Dict

from backend.util.cl2k.gdrive_upload import move_file


def apply_proposal(row: Dict[str, Any], sync_cfg: Any, logger) -> str:
    """Rename per a proposal: the user's Drive first (a failure there is a clean
    no-op), then the local source copy (best-effort — the Drive is canonical, and
    a missing/failed local file reconciles on the next poster_renamerr scan).

    ``row`` needs current_filename, proposed_filename, poster_file, drive_folder_id
    (both a resolver proposal dict and a poster_heal_review row carry these).
    Returns a human note about the local step; raises on a Drive rename failure.
    """
    current = row.get("current_filename") or ""
    proposed = row.get("proposed_filename") or ""
    old_path = row.get("poster_file") or ""
    folder_id = row.get("drive_folder_id")

    if folder_id:
        move_file(current, proposed, folder_id, sync_cfg, logger)

    note = ""
    new_path = os.path.join(os.path.dirname(old_path), proposed)
    try:
        if old_path and os.path.exists(old_path):
            os.replace(old_path, new_path)
            logger.info(f"renamed local {current} -> {proposed}")
        elif old_path:
            note = " (local copy was missing; it will refresh on the next scan)"
            logger.warning(f"local file missing, skipped local rename: {old_path}")
    except OSError as exc:
        note = f" (local rename failed: {exc}; it will refresh on the next scan)"
        logger.warning(f"local rename failed for {old_path}: {exc}")
    return note
