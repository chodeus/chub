"""Shared, TTL-guarded refresh of CHUB's ``plex_media_cache`` snapshot.

The "plex" apply paths (poster upload, asset_renamerr direct apply) resolve
artwork targets from ``plex_media_cache`` via :class:`PlexMediaIndex`. That cache
is only as fresh as the last Plex walk, so before building the index a run
should refresh it — but chained/back-to-back runs shouldn't each re-walk the
whole library. This helper walks Plex at most once per TTL window: it checks the
cache's ``updated_at`` age (per instance *and* library) and skips the walk when
the snapshot is already fresh. The poster/asset apply paths additionally have a
lazy per-item live fallback that covers items added in the gap between refresh
and apply; callers that read the snapshot directly (e.g. labelarr) instead rely
on the per-library freshness check so a never-walked library is always refreshed.
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

    # Fresh-enough? Skip the walk. Scope the check to each (instance, library)
    # we care about: a library that was never walked (age None) or is older than
    # the TTL forces a refresh, even when the instance's other libraries are
    # fresh. A per-instance MAX would let one fresh library mask a stale/missing
    # sibling — silently skipping it for callers (e.g. labelarr) that read the
    # snapshot directly with no live per-item fallback.
    if ttl_seconds > 0:
        oldest = 0.0
        stale = False
        for name, libraries in enabled_instances.items():
            # Empty library list → fall back to an instance-wide freshness check.
            for lib in libraries or [None]:
                age = db.plex.last_synced_age_seconds(name, lib)
                if age is None or age > ttl_seconds:
                    stale = True
                    break
                oldest = max(oldest, age)
            if stale:
                break
        if not stale:
            if logger:
                logger.debug(
                    f"plex_media_cache fresh ({int(oldest)}s ≤ {ttl_seconds}s TTL) "
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
