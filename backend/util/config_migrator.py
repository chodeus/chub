"""Auto-migrate legacy YAML config shapes to the current chub schema.

`load_config()` calls `migrate()` whenever `is_legacy_config()` returns True,
so users dropping in a YAML from an older config format don't have to
hand-edit before chub will load. The detection heuristic only fires on
shape signals that no chub-native config has — see LEGACY_SIGNALS — so
files that have only ever been edited inside chub are a guaranteed no-op.

Everything in this module is pure: it takes a raw dict, returns a new
dict plus a list of MigrationNote entries explaining what changed. File
I/O and Pydantic validation happen in the caller (config.py).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from backend.util.config import _split_legacy_instances


@dataclass
class MigrationNote:
    """One observation about a migration step that ran (or had nothing to do)."""

    rule: str
    message: str
    level: str = "info"  # "info" | "warning"


# ─── Detection ──────────────────────────────────────────────────────────


def _has_path(raw: Any, *path: str) -> bool:
    """Return True iff every key in ``path`` resolves to a non-missing value."""
    d = raw
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return False
        d = d[key]
    return True


def _instance_names_by_type(raw: Dict[str, Any]) -> Tuple[set, set]:
    """Return (plex_names, non_plex_names) from the `instances` registry.

    Used to classify entries listed in module `instances` fields by their
    declared service type, so a Plex name can be told apart from an ARR one.
    """
    plex: set = set()
    non_plex: set = set()
    registry = raw.get("instances")
    if isinstance(registry, dict):
        for service_type, entries in registry.items():
            if not isinstance(entries, dict):
                continue
            names = {n for n in entries if isinstance(n, str)}
            if service_type == "plex":
                plex |= names
            else:
                non_plex |= names
    return plex, non_plex


def is_legacy_config(raw: Dict[str, Any]) -> bool:
    """Heuristic — True iff the dict contains any legacy-only shape signal.

    Every signal below is something the current schema does not produce, so
    a chub-native config returns False here without exception.
    """
    if not isinstance(raw, dict):
        return False

    # Legacy-only sections at the root
    for section in ("main", "discord"):
        if section in raw:
            return True

    # Legacy-only keys nested under known sections
    legacy_keys = [
        ("poster_renamerr", "incremental_border_replacerr"),
        ("unmatched_assets", "ignore_root_folders"),
        ("unmatched_assets", "source_dirs"),
        ("renameinatorr", "ignore_tag"),
        ("poster_cleanarr", "source_dirs"),
        ("poster_cleanarr", "ignore_media"),
    ]
    for path in legacy_keys:
        if _has_path(raw, *path):
            return True

    # Legacy-only value-types on the same key name
    if isinstance(raw.get("poster_cleanarr", {}).get("dry_run"), bool):
        return True
    if isinstance(raw.get("border_replacerr", {}).get("holidays"), dict):
        return True

    # poster_renamerr / asset_renamerr / unmatched_assets: any non-string entry
    # in `instances` is the legacy `{plex_name: {library_names, add_posters}}`
    # shape that the split rule converts into a `plex_scope` list. Detection
    # supersedes the old "deliberately NOT a legacy signal" note — the dict form
    # is now always migrated to plex_scope on load.
    for _mod in ("poster_renamerr", "asset_renamerr", "unmatched_assets"):
        _inst = raw.get(_mod, {}).get("instances")
        if isinstance(_inst, list) and any(not isinstance(i, str) for i in _inst):
            return True

    # `poster_cleanarr.instances` likewise accepted `{plex_name: {...}}` dict
    # entries in the legacy schema (same shape as poster_renamerr). The current
    # schema is `List[str]`, so any non-string element is a legacy shape signal.
    cleanarr_instances = raw.get("poster_cleanarr", {}).get("instances")
    if isinstance(cleanarr_instances, list) and any(
        not isinstance(item, str) for item in cleanarr_instances
    ):
        return True

    # Pre-split `poster_cleanarr`: ARR names were listed in `instances`
    # (shared between the Plex bloat pass and the ARR orphan pass) before
    # `orphan_instances` existed. Mixed ARR names there with no
    # `orphan_instances` set is the pre-split shape.
    cleanarr = raw.get("poster_cleanarr")
    if isinstance(cleanarr, dict) and not cleanarr.get("orphan_instances"):
        cleanarr_instances = cleanarr.get("instances")
        if isinstance(cleanarr_instances, list):
            _, non_plex = _instance_names_by_type(raw)
            if any(
                isinstance(name, str) and name in non_plex
                for name in cleanarr_instances
            ):
                return True

    return False


# ─── Individual rules ───────────────────────────────────────────────────
#
# Each rule:
#   - accepts the current dict + notes list, mutates the dict, appends notes
#   - is a no-op when the legacy field is absent (idempotent)
#   - never assumes the field exists — guards with .get()
#
# The order matters for the `main` moves: we extract the three known fields
# first, then drop the whole section.


def _rule_rename_field(
    raw: Dict[str, Any],
    notes: List[MigrationNote],
    section: str,
    old_key: str,
    new_key: str,
) -> None:
    sec = raw.get(section)
    if not isinstance(sec, dict) or old_key not in sec:
        return
    sec[new_key] = sec.pop(old_key)
    notes.append(
        MigrationNote(
            rule=f"rename:{section}.{old_key}->{new_key}",
            message=f"Renamed `{section}.{old_key}` to `{section}.{new_key}`.",
        )
    )


def _rule_drop_field(
    raw: Dict[str, Any],
    notes: List[MigrationNote],
    section: str,
    key: str,
    reason: str,
) -> None:
    sec = raw.get(section)
    if not isinstance(sec, dict) or key not in sec:
        return
    sec.pop(key)
    notes.append(
        MigrationNote(
            rule=f"drop:{section}.{key}",
            message=f"Dropped `{section}.{key}` — {reason}.",
            level="warning",
        )
    )


def _rule_drop_section(
    raw: Dict[str, Any], notes: List[MigrationNote], section: str, reason: str
) -> None:
    if section not in raw:
        return
    raw.pop(section)
    notes.append(
        MigrationNote(
            rule=f"drop-section:{section}",
            message=f"Dropped `{section}` section — {reason}.",
            level="warning",
        )
    )


def _rule_move_field(
    raw: Dict[str, Any],
    notes: List[MigrationNote],
    src_section: str,
    src_key: str,
    dst_section: str,
    dst_key: str,
    transform: Callable[[Any], Any] = lambda v: v,
) -> None:
    src = raw.get(src_section)
    if not isinstance(src, dict) or src_key not in src:
        return
    value = transform(src.pop(src_key))
    raw.setdefault(dst_section, {})
    if not isinstance(raw[dst_section], dict):
        raw[dst_section] = {}
    raw[dst_section][dst_key] = value
    notes.append(
        MigrationNote(
            rule=f"move:{src_section}.{src_key}->{dst_section}.{dst_key}",
            message=(f"Moved `{src_section}.{src_key}` to `{dst_section}.{dst_key}`."),
        )
    )


def _rule_rename_nested_key_in_labelarr(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """`labelarr.mappings[].plex_instances[].plex_instance` → `instance`."""
    mappings = raw.get("labelarr", {}).get("mappings")
    if not isinstance(mappings, list):
        return
    renamed = 0
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        plex_instances = mapping.get("plex_instances")
        if not isinstance(plex_instances, list):
            continue
        for entry in plex_instances:
            if isinstance(entry, dict) and "plex_instance" in entry:
                entry["instance"] = entry.pop("plex_instance")
                renamed += 1
    if renamed:
        notes.append(
            MigrationNote(
                rule="rename:labelarr.mappings[].plex_instances[].plex_instance->instance",
                message=(
                    f"Renamed `plex_instance` to `instance` on "
                    f"{renamed} labelarr plex mapping entries."
                ),
            )
        )


def _rule_cleanarr_drytun_to_mode(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """`poster_cleanarr.dry_run: bool` → `poster_cleanarr.mode: str`.

    True → "report", False → "remove". If `mode` is already set, the existing
    value wins and we just drop `dry_run`.
    """
    sec = raw.get("poster_cleanarr")
    if not isinstance(sec, dict) or "dry_run" not in sec:
        return
    dry_run = sec.pop("dry_run")
    if "mode" in sec:
        notes.append(
            MigrationNote(
                rule="convert:poster_cleanarr.dry_run->mode",
                message=(
                    "Dropped `poster_cleanarr.dry_run` — `mode` was already "
                    "set and takes precedence."
                ),
            )
        )
        return
    if not isinstance(dry_run, bool):
        # Defensive: if someone wrote `dry_run: "true"` as a string,
        # leave behavior unchanged by dropping silently.
        return
    sec["mode"] = "report" if dry_run else "remove"
    notes.append(
        MigrationNote(
            rule="convert:poster_cleanarr.dry_run->mode",
            message=(
                f"Converted `poster_cleanarr.dry_run: {dry_run}` to "
                f"`mode: {sec['mode']}`."
            ),
        )
    )


def _rule_split_cleanarr_instances(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """Split `poster_cleanarr.instances` into Plex (bloat) + ARR (orphan).

    Pre-split configs listed both the Plex instance (for the bloat pass) and
    Radarr/Sonarr instances (for the orphan-asset pass) in one `instances`
    field. Move the ARR names into the new `orphan_instances` field and leave
    only Plex (plus any unrecognised names) in `instances`. Idempotent: a
    no-op once `orphan_instances` is populated.
    """
    sec = raw.get("poster_cleanarr")
    if not isinstance(sec, dict):
        return
    if sec.get("orphan_instances"):
        return  # already split
    instances = sec.get("instances")
    if not isinstance(instances, list):
        return

    _, non_plex = _instance_names_by_type(raw)
    arr_names = [n for n in instances if isinstance(n, str) and n in non_plex]
    if not arr_names:
        return

    sec["orphan_instances"] = arr_names
    sec["instances"] = [n for n in instances if n not in arr_names]
    notes.append(
        MigrationNote(
            rule="split:poster_cleanarr.instances->orphan_instances",
            message=(
                f"Moved ARR instance(s) {arr_names} from "
                f"`poster_cleanarr.instances` into `orphan_instances` "
                f"(the orphan-asset comparison set). `instances` now holds "
                f"only the Plex instance(s) used by the bloat-image pass."
            ),
        )
    )


def _rule_flatten_cleanarr_instances(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """Flatten `poster_cleanarr.instances` dict entries down to their key.

    Legacy DAPS accepted `{plex_name: {library_names: [...]}}` entries here,
    matching the `poster_renamerr.instances` shape. The current schema only
    accepts strings (the Plex selection drives the bloat-image pass), so the
    inner `library_names` filter is discarded. Runs before the ARR/Plex split
    so the split sees plain name strings. A warning note records what was
    collapsed.
    """
    sec = raw.get("poster_cleanarr")
    if not isinstance(sec, dict):
        return
    items = sec.get("instances")
    if not isinstance(items, list):
        return

    new_items: List[str] = []
    flattened: List[str] = []
    for item in items:
        if isinstance(item, str):
            new_items.append(item)
        elif isinstance(item, dict) and item:
            key = next(iter(item))
            if isinstance(key, str):
                new_items.append(key)
                flattened.append(key)
        # Anything else (None, list, empty dict) is dropped silently.

    if flattened:
        sec["instances"] = new_items
        notes.append(
            MigrationNote(
                rule="flatten:poster_cleanarr.instances",
                message=(
                    f"Flattened legacy dict entries in "
                    f"`poster_cleanarr.instances` to instance names: "
                    f"{flattened}. Per-library filtering is no longer applied "
                    f"here."
                ),
                level="warning",
            )
        )


def _rule_split_module_instances_to_plex_scope(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """Split legacy `{plex_name: {library_names, add_posters}}` dict entries
    in `instances` into a `plex_scope` list for each of the three modules that
    support it. Reuses `_split_legacy_instances` from config.py (single source
    of truth). Idempotent: modules whose `instances` are already all-strings
    are skipped with no note.
    """
    for module in ("poster_renamerr", "asset_renamerr", "unmatched_assets"):
        sec = raw.get(module)
        if not isinstance(sec, dict):
            continue
        split = _split_legacy_instances(sec)
        # _split_legacy_instances returns the SAME object iff nothing changed;
        # value-equality would always be True here and append a spurious note.
        if split is sec:
            continue  # all-string instances — no change
        raw[module] = split
        notes.append(
            MigrationNote(
                rule=f"split:{module}.instances->plex_scope",
                message=(
                    f"Split legacy Plex dict entries out of `{module}.instances` "
                    f"into `{module}.plex_scope`. ARR instance names remain in "
                    f"`instances`."
                ),
            )
        )


def _rule_border_holidays_dict_to_list(
    raw: Dict[str, Any], notes: List[MigrationNote]
) -> None:
    """`border_replacerr.holidays: dict` → `list[{name, schedule, colors, borders}]`."""
    sec = raw.get("border_replacerr")
    if not isinstance(sec, dict):
        return
    holidays = sec.get("holidays")
    if not isinstance(holidays, dict):
        return  # Already a list, or absent

    new_list = []
    for name, body in holidays.items():
        if not isinstance(body, dict):
            continue
        color = body.get("color")
        if isinstance(color, str):
            colors = [color]
        elif isinstance(color, list):
            colors = color
        else:
            colors = []
        new_list.append(
            {
                "name": name,
                "schedule": body.get("schedule"),
                "colors": colors,
                "borders": [],
            }
        )
    sec["holidays"] = new_list
    notes.append(
        MigrationNote(
            rule="convert:border_replacerr.holidays-dict-to-list",
            message=(
                f"Converted `border_replacerr.holidays` from dict to list "
                f"of {len(new_list)} entries."
            ),
        )
    )


# ─── Public entry point ─────────────────────────────────────────────────


def migrate(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], List[MigrationNote]]:
    """Run every migration rule against a deep-copy of ``raw``.

    Returns a tuple of (migrated_dict, notes). The input is never mutated.
    Idempotent: running this on an already-migrated dict produces an empty
    notes list and an unchanged dict.
    """
    out: Dict[str, Any] = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    notes: List[MigrationNote] = []

    # Moves out of `main` before dropping the section
    _rule_move_field(
        out,
        notes,
        "main",
        "log_level",
        "general",
        "log_level",
        transform=lambda v: v.lower() if isinstance(v, str) else v,
    )
    _rule_move_field(out, notes, "main", "theme", "user_interface", "theme")
    _rule_move_field(
        out, notes, "main", "update_notifications", "general", "update_notifications"
    )
    _rule_drop_section(
        out, notes, "main", "fields moved to `general` / `user_interface`"
    )

    # Top-level legacy section that has no chub equivalent
    _rule_drop_section(
        out,
        notes,
        "discord",
        "discord settings are now per-module under `notifications`",
    )

    # Renames
    _rule_rename_field(
        out, notes, "unmatched_assets", "ignore_root_folders", "ignore_folders"
    )
    _rule_rename_field(out, notes, "renameinatorr", "ignore_tag", "ignore_tags")
    _rule_rename_field(out, notes, "poster_cleanarr", "source_dirs", "asset_dirs")
    _rule_rename_nested_key_in_labelarr(out, notes)

    # Drops
    _rule_drop_field(
        out,
        notes,
        "poster_renamerr",
        "incremental_border_replacerr",
        "incremental border-replacer was removed",
    )
    _rule_drop_field(
        out,
        notes,
        "unmatched_assets",
        "source_dirs",
        "source dirs are now derived from `poster_renamerr.source_dirs`",
    )
    _rule_drop_field(
        out,
        notes,
        "poster_cleanarr",
        "ignore_media",
        "per-title ignore is now handled via instance-level filters",
    )

    # Shape conversions
    _rule_split_module_instances_to_plex_scope(out, notes)
    _rule_flatten_cleanarr_instances(out, notes)
    _rule_split_cleanarr_instances(out, notes)

    # Type conversions
    _rule_cleanarr_drytun_to_mode(out, notes)
    _rule_border_holidays_dict_to_list(out, notes)

    return out, notes
