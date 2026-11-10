"""A cached row's own *arr instance: found by its stored type, checked against the client."""

from typing import Any, Dict, Optional

ARR_TYPES = ("radarr", "sonarr", "lidarr")

# Rows whose arr_id names their own whole *arr item. A Sonarr season row carries its
# series' id and a Lidarr album row an album id, which the artist endpoints misread.
_WHOLE_ITEMS = {("radarr", "movie"), ("sonarr", "show"), ("lidarr", "artist")}


def row_kind(row: Dict[str, Any]) -> str:
    """The row's *arr type, lowercased."""
    # Rows written before upsert lowercased it carry "Sonarr".
    return str(row.get("source") or "").lower()


def instance_detail(instances: Any, row: Dict[str, Any]) -> Any:
    """The row's own instance config: under its stored type, else the first name match."""
    # Names are unique only within a type, so a stored type is never second-guessed.
    kind = row_kind(row)
    kinds = (kind,) if kind in ARR_TYPES else ARR_TYPES
    for arr_type in kinds:
        detail = (getattr(instances, arr_type, None) or {}).get(row.get("instance_name"))
        if detail is not None:
            return detail
    return None


def wrong_client(client: Any, kind: str, name: str) -> Optional[str]:
    """Why ``client`` must not act for a ``kind`` row, or None when it may."""
    if str(getattr(client, "instance_type", "")).lower() != kind:
        return f"{name} is not a {kind.capitalize()} instance"
    return None


def whole_item(row: Dict[str, Any]) -> bool:
    """Whether the row's arr_id is its own whole movie, series or artist."""
    # season_number 0 is Specials: still a season row carrying the series' id.
    return (row_kind(row), row.get("asset_type")) in _WHOLE_ITEMS and row.get(
        "season_number"
    ) is None
