# util/gdrive_presets.py

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
PRESETS_PATH = _ASSETS / "gdrive_presets.json"
MOVES_PATH = _ASSETS / "gdrive_preset_moves.json"

_presets_cache: Optional[List[dict]] = None
_moves_cache: Optional[Dict[str, Optional[str]]] = None

_log = logging.getLogger("chub.config")


def load_presets() -> List[dict]:
    """Bundled preset catalogue, parsed once and cached."""
    global _presets_cache
    if _presets_cache is None:
        with open(PRESETS_PATH, "r", encoding="utf-8") as fh:
            _presets_cache = json.load(fh)
    return _presets_cache


def load_moves() -> Dict[str, Optional[str]]:
    """Dropped preset ids: ``{old_id: new_id}``. ``None`` = no replacement known yet."""
    global _moves_cache
    if _moves_cache is None:
        with open(MOVES_PATH, "r", encoding="utf-8") as fh:
            _moves_cache = {
                row["from"]: row.get("to") for row in json.load(fh) if row.get("from")
            }
    return _moves_cache


def reconcile_gdrive_list(entries: Iterable[Any], logger: Any = None) -> int:
    """Repoint saved gdrive_list entries by preset id; never rewrite ``location``.

    Matching is by id, not name — names have been reformatted over time, so
    name matching finds nothing on real configs.
    """
    log = logger or _log
    try:
        moves = load_moves()
    except Exception as exc:
        # Fail OPEN, but loudly: the move table is bundled in the image, so a
        # read failure means a broken image, not a bad user config — refusing to
        # load config at all would take the app down over a cosmetic heal.
        _log.error(f"GDrive preset move table unreadable, ids not reconciled: {exc}")
        return 0

    healed = 0
    for entry in entries or []:
        current = getattr(entry, "id", None) or ""
        if current not in moves:
            continue
        name = getattr(entry, "name", None) or current
        new_id = moves[current]
        if new_id is None:
            # No replacement id known — the drive may be withdrawn, or merely
            # moved somewhere nobody has tracked down yet. Don't tell the user
            # to delete it; a later release can fill in "to" and heal them.
            log.warning(
                f"GDrive preset '{name}' ({current}) is no longer in the bundled "
                "catalogue and syncs nothing. Check for an updated share link from "
                "its owner, or remove it from Settings → sync_gdrive."
            )
            continue
        entry.id = new_id
        healed += 1
        log.warning(
            f"GDrive preset '{name}' moved: {current} -> {new_id}. Using the new id; "
            "save Settings to persist it."
        )
    return healed
