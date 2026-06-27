# backend/util/database/poster_heal_review.py
"""poster_heal_review table — proposed id/title fixes awaiting manual review.

One row per poster file (the local CL2K source copy). The scheduled
poster_self_heal run upserts proposals here; the review UI lists them and the
apply endpoint rewrites the file on disk + the user's Drive, then marks the row
applied. Registered as an extension table via
backend/extensions/poster_self_heal/manifest.py ``tables()`` and accessed through
``db.extension_interface`` (extensions can't add ChubDB properties).
"""

import datetime
from typing import Any, Dict, List, Optional

from .db_base import DatabaseBase

# Statuses a row moves through. "proposed"/"pending" are open (shown for review);
# "applied"/"dismissed" are terminal and sticky across re-scans.
OPEN_STATUSES = ("proposed", "pending")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class PosterHealReview(DatabaseBase):
    """Read/write interface for the poster_heal_review table."""

    def upsert(self, rec: Dict[str, Any]) -> None:
        """Insert or refresh a proposal, keyed on poster_file. A row already
        resolved (applied/dismissed) keeps that status so it isn't re-surfaced."""
        self.execute_query(
            """
            INSERT INTO poster_heal_review
                (poster_file, drive_folder_id, asset_type, drift_type,
                 current_filename, proposed_filename, tmdb_id_old, tmdb_id_new,
                 title_old, title_new, confidence, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(poster_file) DO UPDATE SET
                drive_folder_id=excluded.drive_folder_id,
                asset_type=excluded.asset_type,
                drift_type=excluded.drift_type,
                current_filename=excluded.current_filename,
                proposed_filename=excluded.proposed_filename,
                tmdb_id_old=excluded.tmdb_id_old,
                tmdb_id_new=excluded.tmdb_id_new,
                title_old=excluded.title_old,
                title_new=excluded.title_new,
                confidence=excluded.confidence,
                reason=excluded.reason,
                created_at=excluded.created_at,
                status=CASE
                    WHEN poster_heal_review.status IN ('applied', 'dismissed')
                    THEN poster_heal_review.status
                    ELSE excluded.status
                END
            """,
            (
                rec.get("poster_file"),
                rec.get("drive_folder_id"),
                rec.get("asset_type"),
                rec.get("drift_type"),
                rec.get("current_filename"),
                rec.get("proposed_filename"),
                rec.get("tmdb_id_old"),
                rec.get("tmdb_id_new"),
                rec.get("title_old"),
                rec.get("title_new"),
                rec.get("confidence"),
                rec.get("reason"),
                rec.get("status", "proposed"),
                _now(),
            ),
        )

    def list_open(self, limit: int = 500) -> List[Dict[str, Any]]:
        return (
            self.execute_query(
                "SELECT * FROM poster_heal_review WHERE status IN ('proposed', 'pending') "
                "ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (limit,),
                fetch_all=True,
            )
            or []
        )

    def open_count(self) -> int:
        row = self.execute_query(
            "SELECT COUNT(*) AS n FROM poster_heal_review "
            "WHERE status IN ('proposed', 'pending')",
            fetch_one=True,
        )
        return int(row["n"]) if row else 0

    def get(self, review_id: int) -> Optional[Dict[str, Any]]:
        return self.execute_query(
            "SELECT * FROM poster_heal_review WHERE id = ?",
            (review_id,),
            fetch_one=True,
        )

    def set_status(self, review_id: int, status: str) -> None:
        self.execute_query(
            "UPDATE poster_heal_review SET status = ? WHERE id = ?",
            (status, review_id),
        )

    def delete(self, review_id: int) -> None:
        self.execute_query("DELETE FROM poster_heal_review WHERE id = ?", (review_id,))

    def clear(self) -> None:
        self.execute_query("DELETE FROM poster_heal_review")


def poster_heal_review_table():
    """TableDefinition for poster_heal_review. Imported lazily by the manifest's
    tables() hook (TableDefinition lives in schema.py, imported here not at
    module level to avoid circular imports during config init)."""
    from .schema import ColumnDefinition, TableDefinition

    return TableDefinition(
        name="poster_heal_review",
        columns=[
            ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
            ColumnDefinition("poster_file", "TEXT", nullable=False, unique=True),
            ColumnDefinition("drive_folder_id", "TEXT"),
            ColumnDefinition("asset_type", "TEXT"),
            ColumnDefinition("drift_type", "TEXT"),  # id | title | backfill
            ColumnDefinition("current_filename", "TEXT"),
            ColumnDefinition("proposed_filename", "TEXT"),
            ColumnDefinition("tmdb_id_old", "INTEGER"),
            ColumnDefinition("tmdb_id_new", "INTEGER"),
            ColumnDefinition("title_old", "TEXT"),
            ColumnDefinition("title_new", "TEXT"),
            ColumnDefinition("confidence", "REAL"),
            ColumnDefinition("reason", "TEXT"),
            ColumnDefinition("status", "TEXT", default="proposed"),
            ColumnDefinition("created_at", "TEXT"),
        ],
    )


def poster_heal_review_for(db) -> "PosterHealReview":
    """Accessor — extensions query via db.extension_interface, not ChubDB props."""
    return db.extension_interface("poster_heal_review", PosterHealReview)
