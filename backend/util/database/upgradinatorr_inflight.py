import datetime
from typing import Any, Dict, Optional

from .db_base import DatabaseBase


class UpgradinatorrInflight(DatabaseBase):
    """The search a run stopped waiting on, one per instance, for the next run to finish."""

    def get(self, instance_name: str) -> Optional[Dict[str, Any]]:
        row = self.execute_query(
            "SELECT * FROM upgradinatorr_inflight WHERE instance_name=?",
            (instance_name,),
            fetch_one=True,
        )
        return dict(row) if row else None

    def stage(
        self,
        instance_name: str,
        media_id: int,
        child_id: Optional[str],
        command_id: int,
        label: str,
        started_at: Optional[str] = None,
    ) -> None:
        started = started_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.execute_query(
            """
            INSERT INTO upgradinatorr_inflight
                (instance_name, media_id, child_id, command_id, label, started_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_name) DO UPDATE SET
                media_id = excluded.media_id,
                child_id = excluded.child_id,
                command_id = excluded.command_id,
                label = excluded.label,
                started_at = excluded.started_at
            """,
            (instance_name, media_id, child_id, command_id, label, started),
        )

    def clear(self, instance_name: str) -> None:
        self.execute_query(
            "DELETE FROM upgradinatorr_inflight WHERE instance_name=?",
            (instance_name,),
        )
