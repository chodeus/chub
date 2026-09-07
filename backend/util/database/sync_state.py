from typing import Optional

from .db_base import DatabaseBase


class SyncState(DatabaseBase):
    """Per-(scope, instance) timestamp of the last *completed* sync.

    Cache tables only bump a row's updated_at when that row changes, so they
    track "last row change", not "last sync" — a stable library would look
    stale right after a fresh sync. This table is written once when a sync run
    finishes, giving an accurate "Synced N ago" signal regardless of churn.

    `scope` is the service type ("radarr", "sonarr", "lidarr", "plex"), so
    instance names are namespaced per service.
    """

    def mark_synced(self, scope: str, instance_name: str) -> None:
        """Record that `(scope, instance_name)` just finished syncing."""
        self.execute_query(
            """
            INSERT INTO sync_state (scope, instance_name, synced_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(scope, instance_name) DO UPDATE SET
                synced_at = CURRENT_TIMESTAMP
            """,
            (scope, instance_name),
        )

    def age_seconds(self, scope: str, instance_name: str) -> Optional[float]:
        """Seconds since the last completed sync for this instance, or None if
        it has never been recorded. Uses SQLite's clock so it can't drift from
        the CURRENT_TIMESTAMP values written on mark_synced."""
        row = self.execute_query(
            "SELECT CAST(strftime('%s','now') - strftime('%s', synced_at) AS REAL) AS age "
            "FROM sync_state WHERE scope=? AND instance_name=?",
            (scope, instance_name),
            fetch_one=True,
        )
        if not row or row.get("age") is None:
            return None
        try:
            return max(0.0, float(row["age"]))
        except (TypeError, ValueError):
            return None
