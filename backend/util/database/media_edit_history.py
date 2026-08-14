"""media_edit_history table access, mixed into MediaCache."""

from typing import Any

from .db_base import DatabaseBase


class EditHistoryMixin(DatabaseBase):
    """Append-and-read access to the per-media edit audit trail."""

    def record_edit(
        self,
        media_id: int,
        edited_at: str,
        edited_by: str,
        field: str,
        old_value: Any,
        new_value: Any,
    ) -> None:
        """Append one field's old→new change to the media edit audit trail."""
        self.execute_query(
            "INSERT INTO media_edit_history "
            "(media_id, edited_at, edited_by, field, old_value, new_value) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                media_id,
                edited_at,
                edited_by,
                field,
                None if old_value is None else str(old_value),
                None if new_value is None else str(new_value),
            ),
        )

    def get_edit_history(self, media_id: int, limit: int = 100) -> list:
        """Return one media item's edit audit trail, newest first."""
        return (
            self.execute_query(
                "SELECT * FROM media_edit_history WHERE media_id=? "
                "ORDER BY edited_at DESC, id DESC LIMIT ?",
                (media_id, limit),
                fetch_all=True,
            )
            or []
        )
