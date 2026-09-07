"""In-memory TTL cache for live-discovered Plex library lists (the catalog).

Pure/injectable: `now` and `fetch` are passed in so it is unit-testable and
free of wall-clock calls. Plex remains the source of truth; this only avoids
re-hitting it on every Instances-page / module-picker render."""

from typing import Callable, Dict, List, Optional, Tuple

# instance_name -> (expires_at_epoch, libraries)
_CACHE: Dict[str, Tuple[float, List[dict]]] = {}


def get_cached_libraries(
    instance: str,
    fetch: Callable[[str], List[dict]],
    ttl_seconds: float,
    now: float,
) -> List[dict]:
    entry = _CACHE.get(instance)
    if entry and entry[0] > now:
        return entry[1]
    libs = fetch(instance)
    _CACHE[instance] = (now + ttl_seconds, libs)
    return libs


def invalidate(instance: Optional[str] = None) -> None:
    if instance is None:
        _CACHE.clear()
    else:
        _CACHE.pop(instance, None)
