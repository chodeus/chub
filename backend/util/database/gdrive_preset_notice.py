from typing import Iterable, Set

from .db_base import DatabaseBase


# Not config.yml: a Settings save posts the whole config back and would undo a
# dismissal made while the page was open.
class GdrivePresetNotice(DatabaseBase):
    """Preset ids the new-preset notice no longer shows (first-start baseline + dismissals)."""

    def seen_ids(self) -> Set[str]:
        rows = self.execute_query("SELECT preset_id FROM gdrive_preset_notice", fetch_all=True)
        return {row["preset_id"] for row in rows or []}

    def mark_seen(self, preset_ids: Iterable[str]) -> None:
        for preset_id in preset_ids:
            self.execute_query(
                "INSERT OR IGNORE INTO gdrive_preset_notice (preset_id) VALUES (?)",
                (preset_id,),
            )
