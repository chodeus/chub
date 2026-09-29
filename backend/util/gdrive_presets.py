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


def reconcile_gdrive_list(entries: Iterable[Any], logger: Any = None) -> Optional[int]:
    """Repoint saved gdrive_list entries by preset id; never rewrite ``location``.

    Returns the number healed, or None when the move table could not be read so
    the caller can avoid caching an unreconciled config. Matching is by id, not
    name — names have been reformatted over time and match nothing on real configs.
    """
    log = logger or _log
    try:
        moves = load_moves()
    except Exception as exc:
        # Fail OPEN, but loudly: the move table is bundled in the image, so a
        # read failure means a broken image, not a bad user config — refusing to
        # load config at all would take the app down over a cosmetic heal.
        _log.error(f"GDrive preset move table unreadable, ids not reconciled: {exc}")
        return None

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


def new_presets(sync_cfg: Any, db: Any) -> List[dict]:
    """Presets the new-preset notice shows: neither seen nor already in gdrive_list."""
    seen = db.gdrive_preset_notice.seen_ids()
    if not seen:
        return []
    # A drive already seen under its old id is not news after a move
    seen |= {new for old, new in load_moves().items() if new and old in seen}
    skip = seen | {getattr(e, "id", "") for e in getattr(sync_cfg, "gdrive_list", None) or []}
    return [p for p in load_presets() if p.get("id") and p["id"] not in skip]


def mark_presets_seen(db: Any, ids: Optional[Iterable[str]] = None) -> None:
    """Stop showing ``ids``; all presets when None or when nothing is recorded yet."""
    catalogue = [p["id"] for p in load_presets() if p.get("id")]
    table = db.gdrive_preset_notice
    wanted = set(catalogue) if ids is None or not table.seen_ids() else set(ids)
    # Only catalogue ids are stored, so the table stays bounded by the catalogue
    table.mark_seen([i for i in catalogue if i in wanted])


def announce_new_presets(db: Any, sync_cfg: Any, logger: Any = None) -> List[dict]:
    """Startup: baseline the notice on first run, otherwise log presets still new."""
    log = logger or _log
    if not db.gdrive_preset_notice.seen_ids():
        # First start with the notice: the catalogue as shipped today is not news
        mark_presets_seen(db)
        return []
    fresh = new_presets(sync_cfg, db)
    if fresh:
        names = ", ".join(f"{p['name']} ({p['style']})" for p in fresh)
        log.info(
            f"New GDrive presets available: {names}. Add them in Settings → Sync GDrive, "
            "or dismiss the notice in the web UI."
        )
    return fresh
