"""Shared, TTL-guarded refresh of CHUB's ``plex_media_cache`` snapshot.

The "plex" apply paths (poster upload, asset_renamerr direct apply) resolve
artwork targets from ``plex_media_cache`` via :class:`PlexMediaIndex`. That cache
is only as fresh as the last Plex walk, so before building the index a run
should refresh it — but chained/back-to-back runs shouldn't each re-walk the
whole library. This helper walks Plex at most once per TTL window: it checks the
cache's ``updated_at`` age and skips the walk when the snapshot is already
fresh. A lazy per-item live fallback at the call site still covers items added
in the gap between refresh and apply.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def refresh_plex_cache_if_stale(
    db: Any,
    full_config: Any,
    logger: Any,
    enabled_instances: Dict[str, List[str]],
    *,
    ttl_seconds: Optional[int] = None,
) -> bool:
    """Refresh plex_media_cache for ``enabled_instances`` unless it's fresh.

    Returns True if a Plex walk was performed, False if the cached snapshot was
    reused (fresh within ttl_seconds) or there was nothing to refresh. Never
    raises for an empty instance set; connector errors propagate to the caller.

    ttl_seconds defaults to ``general.plex_cache_ttl_seconds`` (5 min). 0 forces
    a refresh every call.
    """
    if not enabled_instances:
        return False

    if ttl_seconds is None:
        ttl_seconds = int(
            getattr(getattr(full_config, "general", None), "plex_cache_ttl_seconds", 300)
        )

    # Fresh-enough? Skip the walk. (Age None = empty cache / no timestamp =>
    # must refresh.) Scope the freshness check to the instances we care about.
    if ttl_seconds > 0:
        ages = []
        stale = False
        for name in enabled_instances:
            age = db.plex.last_synced_age_seconds(name)
            if age is None:
                stale = True
                break
            ages.append(age)
        if not stale and ages and max(ages) <= ttl_seconds:
            if logger:
                logger.debug(
                    f"plex_media_cache fresh ({int(max(ages))}s ≤ {ttl_seconds}s TTL) "
                    "— reusing snapshot, skipping Plex re-walk"
                )
            return False

    from backend.util.connector import Connector

    instance_map = {"plex": dict(enabled_instances)}
    connector = Connector(db=db, logger=logger, instance_map=instance_map)
    connector.update_plex_database()
    if logger:
        logger.debug("plex_media_cache refreshed from Plex")
    return True
