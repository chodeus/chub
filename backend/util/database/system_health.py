# util/database/system_health.py

from typing import Any, Dict, List, Optional

from .db_base import DatabaseBase


class SystemHealth(DatabaseBase):
    """Read access to the periodic instance-health probes the scheduler records.

    Rows are append-only snapshots of one (instance, service) probe; the
    scheduler owns writing and pruning them.
    """

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
        """The most recent snapshot row for each instance."""
        rows = self.execute_query(
            """
            SELECT s.instance_name, s.service, s.status, s.response_time_ms,
                   s.status_code, s.snapshot_at, s.error
            FROM system_health_snapshots s
            INNER JOIN (
              SELECT instance_name, MAX(snapshot_at) AS latest
              FROM system_health_snapshots GROUP BY instance_name
            ) latest ON s.instance_name = latest.instance_name
                    AND s.snapshot_at = latest.latest
            """,
            fetch_all=True,
        )
        return [dict(r) for r in rows or []]
