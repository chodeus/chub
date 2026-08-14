"""
Poster Cleanarr settings and job-request contract.

Reads the `poster_cleanarr` config section on behalf of the UI/API layer and
turns a cleanup request body into the overrides a `module_run` job expects.
"""

from typing import List, Optional

from backend.util.config import ConfigError


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


def build_cleanup_overrides(body: dict) -> dict:
    """Assemble the poster_cleanarr job overrides from a cleanup request body.
    Raises ValueError on an invalid mode (the route maps it to a 400). Bloat
    accepts "nothing" so the UI can run stale/orphan cleanup with bloat off."""
    mode = (body.get("mode") or "report").lower()
    if mode not in ("report", "move", "remove", "nothing"):
        raise ValueError(f"Invalid mode '{mode}'")
    overrides: dict = {"mode": mode}

    target_paths = body.get("target_paths")
    if isinstance(target_paths, list) and target_paths:
        overrides["target_paths"] = [str(p) for p in target_paths]

    if "orphan_assets_enabled" in body:
        overrides["orphan_assets_enabled"] = bool(body.get("orphan_assets_enabled"))
    orphan_mode = body.get("orphan_assets_mode")
    if isinstance(orphan_mode, str):
        orphan_mode = orphan_mode.lower()
        if orphan_mode not in ("report", "move", "remove"):
            raise ValueError(f"Invalid orphan_assets_mode '{orphan_mode}'")
        overrides["orphan_assets_mode"] = orphan_mode

    if "stale_duplicates_enabled" in body:
        overrides["stale_duplicates_enabled"] = bool(
            body.get("stale_duplicates_enabled")
        )
    stale_mode = body.get("stale_duplicates_mode")
    if isinstance(stale_mode, str):
        stale_mode = stale_mode.lower()
        if stale_mode not in ("report", "move", "remove"):
            raise ValueError(f"Invalid stale_duplicates_mode '{stale_mode}'")
        overrides["stale_duplicates_mode"] = stale_mode

    asset_dirs = body.get("asset_dirs")
    if isinstance(asset_dirs, list):
        overrides["asset_dirs"] = [str(p) for p in asset_dirs]

    if "overlays_only" in body:
        overrides["overlays_only"] = bool(body.get("overlays_only"))
    return overrides
