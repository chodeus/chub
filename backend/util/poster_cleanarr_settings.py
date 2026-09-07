"""
Poster Cleanarr settings and job-request contract.

Reads the `poster_cleanarr` config section on behalf of the UI/API layer and
turns a cleanup request body into the overrides a `module_run` job expects.
"""

from typing import Any, List, Optional

from backend.util.config import ChubConfig, ConfigError
from backend.util.path_safety import resolve_confined


def get_plex_path() -> Optional[str]:
    """
    Resolve the Plex filesystem path from config. The poster_cleanarr module
    config is the canonical place — general config doesn't store this.
    """
    try:
        from backend.util.config import load_config

        cfg = load_config()
    except ConfigError:
        raise
    except Exception:
        return None
    section = getattr(cfg, "poster_cleanarr", None)
    if section is not None:
        pp = getattr(section, "plex_path", None)
        if pp:
            return str(pp)
    return None


def get_excluded_libraries() -> List[str]:
    """Plex library names the user opted out of in poster_cleanarr config.

    Display-side mirror of the module's deletion-side deny-list — hides excluded
    libraries from the by-media view and its libraries[] catalog. A malformed
    config propagates (CONFIG_INVALID); other failures return [] (show
    everything). This is a UI filter, not a safety guard — the in-use set is
    global regardless of any opt-out.
    """
    try:
        from backend.util.config import load_config

        cfg = load_config()
    except ConfigError:
        raise
    except Exception:
        return []
    section = getattr(cfg, "poster_cleanarr", None)
    if section is None:
        return []
    return list(getattr(section, "excluded_libraries", None) or [])


def _require_bool(body: dict, key: str) -> bool:
    """Return body[key] only when it is a real bool."""
    # bool("false") is True — coercing would silently enable a deleting pass.
    value = body.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Invalid {key} type: {type(value).__name__}")
    return value


def _validate_sub_mode(value: Any, key: str) -> Optional[str]:
    """Lowercase an orphan/stale sub-mode; None when absent, ValueError when malformed."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {key} type: {type(value).__name__}")
    mode = value.lower()
    if mode not in ("report", "move", "remove"):
        raise ValueError(f"Invalid {key} '{mode}'")
    return mode


def build_cleanup_overrides(body: dict, config: ChubConfig) -> dict:
    """Assemble the poster_cleanarr job overrides from a cleanup request body.
    Raises ValueError on a malformed field type, an invalid mode, or an
    asset_dir outside the allowed roots (the route maps it to a 400). Bloat
    accepts "nothing" so the UI can run stale/orphan cleanup with bloat off."""
    raw_mode = body.get("mode")
    if raw_mode is None:
        mode = "report"
    elif isinstance(raw_mode, str):
        mode = raw_mode.lower() or "report"
    else:
        raise ValueError(f"Invalid mode type: {type(raw_mode).__name__}")
    if mode not in ("report", "move", "remove", "nothing"):
        raise ValueError(f"Invalid mode '{mode}'")
    overrides: dict = {"mode": mode}

    target_paths = body.get("target_paths")
    if isinstance(target_paths, list) and target_paths:
        overrides["target_paths"] = [str(p) for p in target_paths]

    if "orphan_assets_enabled" in body:
        overrides["orphan_assets_enabled"] = _require_bool(
            body, "orphan_assets_enabled"
        )
    orphan_mode = _validate_sub_mode(
        body.get("orphan_assets_mode"), "orphan_assets_mode"
    )
    if orphan_mode is not None:
        overrides["orphan_assets_mode"] = orphan_mode

    if "stale_duplicates_enabled" in body:
        overrides["stale_duplicates_enabled"] = _require_bool(
            body, "stale_duplicates_enabled"
        )
    stale_mode = _validate_sub_mode(
        body.get("stale_duplicates_mode"), "stale_duplicates_mode"
    )
    if stale_mode is not None:
        overrides["stale_duplicates_mode"] = stale_mode

    asset_dirs = body.get("asset_dirs")
    if isinstance(asset_dirs, list):
        # These reach PosterCleanarr's orphan/stale passes, which DELETE —
        # confine here so no caller can hand it an unchecked request path.
        confined = []
        for p in asset_dirs:
            real = resolve_confined(str(p), config)
            if real is None:
                raise ValueError(f"asset_dirs path is outside the allowed roots: {p}")
            confined.append(str(real))
        overrides["asset_dirs"] = confined

    if "overlays_only" in body:
        overrides["overlays_only"] = _require_bool(body, "overlays_only")
    return overrides
