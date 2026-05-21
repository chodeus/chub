import datetime
from typing import Set

from .db_base import DatabaseBase


class UpgradinatorrProgress(DatabaseBase):
    """Per-(instance, media_id) record of seasons/albums already searched in
    season_album count_mode runs. Lets rotations resume mid-parent rather than
    re-searching the same children on every run."""

    def get_processed_children(self, instance_name: str, media_id: int) -> Set[str]:
        rows = (
            self.execute_query(
                "SELECT child_id FROM upgradinatorr_progress WHERE instance_name=? AND media_id=?",
                (instance_name, media_id),
                fetch_all=True,
            )
            or []
        )
        return {str(r["child_id"]) for r in rows}

    def record_processed_child(
        self, instance_name: str, media_id: int, child_id: str
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.execute_query(
            """
            INSERT INTO upgradinatorr_progress (instance_name, media_id, child_id, searched_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(instance_name, media_id, child_id) DO UPDATE SET
                searched_at = excluded.searched_at
            """,
            (instance_name, media_id, str(child_id), now),
        )

    def clear_for_media(self, instance_name: str, media_id: int) -> None:
        self.execute_query(
            "DELETE FROM upgradinatorr_progress WHERE instance_name=? AND media_id=?",
            (instance_name, media_id),
        )

    def clear_for_instance(self, instance_name: str) -> None:
        self.execute_query(
            "DELETE FROM upgradinatorr_progress WHERE instance_name=?",
            (instance_name,),
        )
