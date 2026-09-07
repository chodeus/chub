# util/database/tmdb_id_cache.py

import datetime
from typing import Optional, Tuple

from .db_base import DatabaseBase


class TmdbIdCache(DatabaseBase):
    """External-ID → TMDB-ID lookup cache.

    Rows store the result of a TMDB /3/find call so we never re-query for the
    same external id within the configured expiration window. A row with
    tmdb_id NULL is a negative cache (TMDB returned no match); we still respect
    a shorter expiration so newly-added shows on TMDB get re-tried eventually.

    The cache is critical: TMDB enforces ~50 req/s + per-day quotas, and every
    sync would otherwise re-resolve the same IDs.
    """

    NEGATIVE_CACHE_DAYS = 7

    def get(
        self,
        external_id: str,
        source: str,
        media_type: str,
        expiration_days: int,
    ) -> Tuple[bool, Optional[int]]:
        """Return (cache_hit, tmdb_id). cache_hit=False means caller must
        fetch from TMDB. tmdb_id can be None even when cache_hit=True
        (negative cache).
        """
        row = self.execute_query(
            """SELECT tmdb_id, cached_at FROM tmdb_id_cache
               WHERE external_id=? AND source=? AND media_type=?""",
            (external_id, source, media_type),
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

        ttl_days = (
            expiration_days
            if row["tmdb_id"] is not None
            else min(expiration_days, self.NEGATIVE_CACHE_DAYS)
        )
        cutoff = datetime.datetime.now() - datetime.timedelta(days=ttl_days)
        if ts < cutoff:
            return False, None
        return True, row["tmdb_id"]

    def put(
        self,
        external_id: str,
        source: str,
        media_type: str,
        tmdb_id: Optional[int],
    ) -> None:
        """Insert or refresh a cache row. tmdb_id=None records a negative cache."""
        now_iso = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        self.execute_query(
            """INSERT INTO tmdb_id_cache
                   (external_id, source, media_type, tmdb_id, cached_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(external_id, source, media_type)
               DO UPDATE SET tmdb_id=excluded.tmdb_id, cached_at=excluded.cached_at""",
            (external_id, source, media_type, tmdb_id, now_iso),
        )

    def clear(self) -> None:
        self.execute_query("DELETE FROM tmdb_id_cache")
