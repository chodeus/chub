# util/database/tmdb_images_cache.py

import datetime
import json
from typing import Any, Dict, Optional, Tuple

from .db_base import DatabaseBase


class TmdbImagesCache(DatabaseBase):
    """Caches the image URLs selected from TMDB GET /3/{movie|tv}/{id}/images,
    keyed by (tmdb_id, media_type).

    Stores the resolved best-pick URLs ({"logo": ..., "background": ...}) rather
    than the raw API response. Like tmdb_details_cache, expiration is enforced
    here in Python so a single window covers repeated asset_renamerr runs without
    re-hitting TMDB's rate limits.
    """

    def get(
        self,
        tmdb_id: int,
        media_type: str,
        expiration_days: int,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Return (cache_hit, images_dict). cache_hit=False means the caller
        must fetch from TMDB. images_dict is {"logo": url|None, "background":
        url|None}."""
        row = self.execute_query(
            "SELECT images, cached_at FROM tmdb_images_cache "
            "WHERE tmdb_id=? AND media_type=?",
            (int(tmdb_id), media_type),
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

    def put(self, tmdb_id: int, media_type: str, images: Dict[str, Any]) -> None:
        """Insert or refresh the cached image URLs for a (tmdb_id, media_type)."""
        now_iso = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        self.execute_query(
            """INSERT INTO tmdb_images_cache (tmdb_id, media_type, images, cached_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(tmdb_id, media_type)
               DO UPDATE SET images=excluded.images, cached_at=excluded.cached_at""",
            (int(tmdb_id), media_type, json.dumps(images or {}), now_iso),
        )

    def clear(self) -> None:
        self.execute_query("DELETE FROM tmdb_images_cache")
