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
    """Retired/relocated preset ids: ``{old_id: new_id or None}``. ``None`` = retired."""
    global _moves_cache
    if _moves_cache is None:
        with open(MOVES_PATH, "r", encoding="utf-8") as fh:
            _moves_cache = {
                row["from"]: row.get("to") for row in json.load(fh) if row.get("from")
            }
    return _moves_cache


def reconcile_gdrive_list(entries: Iterable[Any], logger: Any = None) -> int:
    """Repoint saved gdrive_list entries whose preset drive moved. Returns the count healed.

    Keyed on the saved ``id``, NOT the name: preset names have been reformatted
    over time (saved "CL2K Dweagle" vs catalogue "Dweagle79"), so name matching
    finds nothing on real configs. A move must be recorded in
    gdrive_preset_moves.json — editing gdrive_presets.json alone reaches new
    picks only, never an existing config.

    ``location`` is deliberately never rewritten: it is a live directory that
    sync_gdrive writes into and source_dirs point at.
    """
    log = logger or _log
    try:
        moves = load_moves()
    except Exception as exc:
        # Fail OPEN: healing an id is a convenience, and refusing to load the
        # whole config over an unreadable catalogue would be far worse.
        _log.debug(f"gdrive preset moves unavailable, skipping reconcile: {exc}")
        return 0

    healed = 0
    for entry in entries or []:
        current = getattr(entry, "id", None) or ""
        if current not in moves:
            continue
        name = getattr(entry, "name", None) or current
        new_id = moves[current]
        if new_id is None:
            log.warning(
                f"GDrive preset '{name}' is retired — that Drive folder is gone. "
                "Remove it from Settings → sync_gdrive, or point it at a live drive."
            )
            continue
        entry.id = new_id
        healed += 1
        log.warning(
            f"GDrive preset '{name}' moved: {current} -> {new_id}. Using the new id; "
            "save Settings to persist it."
        )
    return healed
