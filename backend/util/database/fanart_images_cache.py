# util/database/fanart_images_cache.py

import datetime
import json
from typing import Any, Dict, Optional, Tuple

from .db_base import DatabaseBase


class FanartImagesCache(DatabaseBase):
    """Caches the logo/background URLs selected from the fanart.tv v3 API,
    keyed by (lookup_id, media_type, season).

    ``lookup_id`` is the id fanart is queried with — the tmdb id for movies,
    the tvdb id for TV. ``season`` is -1 for movies and show-level rows; a real
    season number for season-specific backgrounds. Stores the resolved best-pick
    URLs ({"logo": ..., "background": ...}) rather than the raw API response.
    Expiration is enforced here in Python (like tmdb_images_cache) so a single
    window covers repeated asset_renamerr runs without re-hitting fanart's
    servers — required by fanart.tv's "no more requests than necessary" terms.
    """

    @staticmethod
    def _season_key(season: Optional[int]) -> int:
        try:
            return int(season) if season is not None else -1
        except (TypeError, ValueError):
            return -1

    def get(
        self,
        lookup_id: Any,
        media_type: str,
        expiration_days: int,
        season: Optional[int] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Return (cache_hit, images_dict). cache_hit=False means the caller
        must fetch from fanart. images_dict is {"logo": url|None,
        "background": url|None}."""
        row = self.execute_query(
            "SELECT images, cached_at FROM fanart_images_cache "
            "WHERE lookup_id=? AND media_type=? AND season=?",
            (str(lookup_id), media_type, self._season_key(season)),
            fetch_one=True,
        )
        if not row:
            return False, None

        cached_at = row.get("cached_at")
        if not cached_at:
            return False, None
        try:
            ts = datetime.datetime.fromisoformat(cached_at.replace(" ", "T"))
        except (ValueError, AttributeError):
            return False, None

        cutoff = datetime.datetime.now() - datetime.timedelta(days=expiration_days)
        if ts < cutoff:
            return False, None

        try:
            images = json.loads(row.get("images") or "{}")
        except (ValueError, TypeError):
            images = {}
        return True, images

    def put(
        self,
        lookup_id: Any,
        media_type: str,
        images: Dict[str, Any],
        season: Optional[int] = None,
    ) -> None:
        """Insert or refresh the cached image URLs for a
        (lookup_id, media_type, season)."""
        now_iso = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        self.execute_query(
            """INSERT INTO fanart_images_cache
                   (lookup_id, media_type, season, images, cached_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(lookup_id, media_type, season)
               DO UPDATE SET images=excluded.images, cached_at=excluded.cached_at""",
            (
                str(lookup_id),
                media_type,
                self._season_key(season),
                json.dumps(images or {}),
                now_iso,
            ),
        )

    def clear(self) -> None:
        self.execute_query("DELETE FROM fanart_images_cache")
