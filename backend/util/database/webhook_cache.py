# util/database/webhook_cache.py

import datetime
from typing import Optional

from .db_base import DatabaseBase


class WebhookCache(DatabaseBase):
    """
    Persistent webhook dedup cache.

    Sonarr/Radarr retry failed webhooks minutes apart; an in-memory
    debounce window (seconds) won't catch those, and is wiped on restart.
    This table holds a rolling window keyed on (item_type, item_name)
    with a configurable TTL — defaults to 600s.
    """

    DEFAULT_TTL_SECONDS = 600

    def is_duplicate(
        self, item_type: str, item_name: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> bool:
        """
        Check whether `(item_type, item_name)` was seen within `ttl_seconds`.

        Behaviour:
        - Sweeps rows older than the TTL on every call (cheap; the index
          on `timestamp` keeps the scan small).
        - If a non-expired row exists, returns True.
        - Otherwise inserts a fresh row and returns False.

        IntegrityError on the UNIQUE constraint is treated as a duplicate
        (race window between two concurrent webhook calls for the same item).
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff_iso = (now - datetime.timedelta(seconds=ttl_seconds)).isoformat()
        now_iso = now.isoformat()

        with self.get_connection() as conn:
            conn.execute("DELETE FROM webhook_cache WHERE timestamp < ?", (cutoff_iso,))

            existing = conn.execute(
                "SELECT id FROM webhook_cache WHERE item_type = ? AND item_name = ?",
                (item_type, item_name),
            ).fetchone()

            if existing:
                conn.commit()
                return True

            try:
                conn.execute(
                    "INSERT INTO webhook_cache (item_type, item_name, timestamp) "
                    "VALUES (?, ?, ?)",
                    (item_type, item_name, now_iso),
                )
                conn.commit()
                return False
            except Exception:
                conn.rollback()
                return True

    def clear(self) -> None:
        """Drop every row (testing/dev only)."""
        self.execute_query("DELETE FROM webhook_cache")

    def count(self) -> int:
        row = self.execute_query(
            "SELECT COUNT(*) AS n FROM webhook_cache", fetch_one=True
        )
        return int(row["n"]) if row else 0

    def last_seen(self, item_type: str, item_name: str) -> Optional[str]:
        row = self.execute_query(
            "SELECT timestamp FROM webhook_cache WHERE item_type = ? AND item_name = ?",
            (item_type, item_name),
            fetch_one=True,
        )
        return row["timestamp"] if row else None
