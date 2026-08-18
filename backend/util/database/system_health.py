# util/database/system_health.py

from typing import Any, Dict, List, Optional

from .db_base import DatabaseBase


class SystemHealth(DatabaseBase):
    """The periodic instance-health probes: the scheduler records and prunes
    them here; the system API reads them."""

    def record_snapshots(self, rows: List[tuple]) -> None:
        """Append one scheduler pass's probe rows in a single transaction."""
        if not rows:
            return
        self.execute_transaction(
            [
                (
                    "INSERT INTO system_health_snapshots "
                    "(snapshot_at, service, instance_name, status, "
                    "status_code, response_time_ms, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    tuple(row),
                )
                for row in rows
            ]
        )

    def prune_snapshots_before(self, cutoff: str) -> int:
        """Delete snapshots older than the cutoff; returns rows removed."""
        # TEXT compare on purpose: one writer/clock, and datetime() wrapping
        # would forfeit system_health_time_idx.
        return (
            self.execute_query(
                "DELETE FROM system_health_snapshots WHERE snapshot_at < ?",
                (cutoff,),
            )
            or 0
        )

    def recent_snapshots(
        self, limit: int = 50, instance: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Newest snapshots, optionally for one instance."""
        # `, id DESC` breaks ties: probes in one scheduler pass share snapshot_at,
        # so without it the LIMIT window would be arbitrary.
        if instance:
            rows = self.execute_query(
                "SELECT * FROM system_health_snapshots WHERE instance_name=? "
                "ORDER BY snapshot_at DESC, id DESC LIMIT ?",
                (instance, limit),
                fetch_all=True,
            )
        else:
            rows = self.execute_query(
                "SELECT * FROM system_health_snapshots "
                "ORDER BY snapshot_at DESC, id DESC LIMIT ?",
                (limit,),
                fetch_all=True,
            )
        return [dict(r) for r in rows or []]

    def latest_per_instance(self) -> List[Dict[str, Any]]:
        """The most recent snapshot row for each (instance, service) pair."""
        rows = self.execute_query(
            """
            SELECT instance_name, service, status, response_time_ms,
                   status_code, snapshot_at, error
            FROM (
              SELECT s.*, ROW_NUMBER() OVER (
                       PARTITION BY instance_name, service
                       ORDER BY snapshot_at DESC, id DESC
                     ) AS rn
              FROM system_health_snapshots s
            )
            WHERE rn = 1
            """,
            fetch_all=True,
        )
        return [dict(r) for r in rows or []]
