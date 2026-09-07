import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .db_base import DatabaseBase


class UpgradinatorrGrabs(DatabaseBase):
    """Grabs this module made, held until their import outcome is known.

    A run ends when the search is issued — the download has not imported yet,
    so "did this actually upgrade a file?" can only be answered by a LATER run
    reading the *arr's history. These rows are that hand-off.
    """

    def record(
        self,
        instance_name: str,
        grabs: Sequence[Dict[str, Any]],
        grabbed_at: Optional[str] = None,
    ) -> None:
        """Store this run's grabs. Re-recording a download_id is a no-op.

        ``grabbed_at`` should be the run's start, not now: it becomes the
        history lookback floor, and a fast import can land before the run ends.
        """
        now = grabbed_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        for grab in grabs:
            download_id = str(grab.get("download_id") or "").strip()
            if not download_id:
                continue
            self.execute_query(
                """
                INSERT INTO upgradinatorr_grabs
                    (instance_name, download_id, media_id, title, year, release_title, score, grabbed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_name, download_id) DO NOTHING
                """,
                (
                    instance_name,
                    download_id,
                    grab.get("media_id"),
                    grab.get("title"),
                    grab.get("year"),
                    grab.get("release_title"),
                    grab.get("score"),
                    now,
                ),
            )

    def pending(self, instance_name: str) -> List[Dict[str, Any]]:
        """Grabs still awaiting an import outcome, oldest first."""
        rows = self.execute_query(
            "SELECT * FROM upgradinatorr_grabs WHERE instance_name=? ORDER BY grabbed_at",
            (instance_name,),
            fetch_all=True,
        )
        return list(rows or [])

    def oldest_pending(self, instance_name: str) -> Optional[str]:
        """ISO timestamp of the oldest pending grab — the history lookback floor."""
        row = self.execute_query(
            "SELECT MIN(grabbed_at) AS oldest FROM upgradinatorr_grabs WHERE instance_name=?",
            (instance_name,),
            fetch_one=True,
        )
        return (row or {}).get("oldest")

    def clear(self, instance_name: str, download_ids: Iterable[str]) -> None:
        """Drop rows whose outcome has been read."""
        for download_id in download_ids:
            self.execute_query(
                "DELETE FROM upgradinatorr_grabs WHERE instance_name=? AND download_id=?",
                (instance_name, str(download_id)),
            )

    def prune(self, instance_name: str, older_than_days: int) -> None:
        """Forget grabs too old to still be downloading — they bound the lookback."""
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=older_than_days
        )
        self.execute_query(
            "DELETE FROM upgradinatorr_grabs WHERE instance_name=? AND grabbed_at < ?",
            (instance_name, cutoff.isoformat()),
        )

    def clear_for_instance(self, instance_name: str) -> None:
        self.execute_query(
            "DELETE FROM upgradinatorr_grabs WHERE instance_name=?",
            (instance_name,),
        )
