# util/database/tmdb_details_cache.py

import datetime
import json
from typing import Any, Dict, Optional, Tuple

from .db_base import DatabaseBase


class TmdbDetailsCache(DatabaseBase):
    """TMDB details cache for the optional ID-verification / AKA-hydration
    features.

    Rows store the result of a TMDB GET /3/{movie|tv}/{id} call (title,
    original_title, year, alternative_titles) keyed by (tmdb_id, media_type).
    `verified=0` is a negative cache (TMDB has no such id) — surfaced to the
    matcher as a mismatch — and is re-tried sooner than positive rows.

    Like tmdb_id_cache, expiration is enforced here in Python, not by SQL, so a
    single window covers repeated syncs without re-hitting TMDB's rate limits.
    """

    NEGATIVE_CACHE_DAYS = 7

    def get(
        self,
        tmdb_id: int,
        media_type: str,
        expiration_days: int,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Return (cache_hit, details). cache_hit=False means the caller must
        fetch from TMDB. details is a dict with keys title/original_title/year/
        alternative_titles/verified, or None for a fresh negative-cache row.
        """
        row = self.execute_query(
            """SELECT title, original_title, year, alternative_titles,
                      verified, cached_at
               FROM tmdb_details_cache
               WHERE tmdb_id=? AND media_type=?""",
            (tmdb_id, media_type),
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

        verified = bool(row.get("verified"))
        ttl_days = (
            expiration_days
            if verified
            else min(expiration_days, self.NEGATIVE_CACHE_DAYS)
        )
        cutoff = datetime.datetime.now() - datetime.timedelta(days=ttl_days)
        if ts < cutoff:
            return False, None

        try:
            alt = json.loads(row.get("alternative_titles") or "[]")
        except (ValueError, TypeError):
            alt = []
        return True, {
            "title": row.get("title"),
            "original_title": row.get("original_title"),
            "year": row.get("year"),
            "alternative_titles": alt,
            "verified": verified,
        }

    def put(
        self,
        tmdb_id: int,
        media_type: str,
        *,
        title: Optional[str] = None,
        original_title: Optional[str] = None,
        year: Optional[int] = None,
        alternative_titles: Optional[list] = None,
        verified: bool = False,
    ) -> None:
        """Insert or refresh a details row. verified=False records a negative
        cache (TMDB returned no such id)."""
        now_iso = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        alt_json = json.dumps(alternative_titles or [])
        self.execute_query(
            """INSERT INTO tmdb_details_cache
                   (tmdb_id, media_type, title, original_title, year,
                    alternative_titles, verified, cached_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(tmdb_id, media_type)
               DO UPDATE SET title=excluded.title,
                             original_title=excluded.original_title,
                             year=excluded.year,
                             alternative_titles=excluded.alternative_titles,
                             verified=excluded.verified,
                             cached_at=excluded.cached_at""",
            (
                tmdb_id,
                media_type,
                title,
                original_title,
                year,
                alt_json,
                int(bool(verified)),
                now_iso,
            ),
        )

    def clear(self) -> None:
        self.execute_query("DELETE FROM tmdb_details_cache")
