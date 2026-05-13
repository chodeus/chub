import os
from typing import Any, List, Optional

from .db_base import DatabaseBase


def _path_under_any_root(path: str, allowed_roots: List[str]) -> bool:
    """True if `path` resolves to a location under any of `allowed_roots`."""
    if not path:
        return False
    try:
        real_path = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    for root in allowed_roots:
        if not root:
            continue
        try:
            real_root = os.path.realpath(root)
        except (OSError, ValueError):
            continue
        if real_path == real_root or real_path.startswith(real_root + os.sep):
            return True
    return False


class PendingDeletions(DatabaseBase):
    """
    Queue of poster files marked for deletion (path-precise cleanup).

    Rows are written when CHUB observes that the media a poster was placed for
    has been removed from Plex/Radarr/Sonarr. Consumers (webhooks, manual
    triggers) process the queue and delete the files + rows.

    Distinct from the filesystem-walk "orphan asset cleanup" in
    `poster_cleanarr` — that one re-discovers stranded files by comparing
    titles against the current library; this one is an event-driven ledger.
    """

    def list_pending(self) -> list:
        """Returns all queued deletions as a list of dicts."""
        return (
            self.execute_query("SELECT * FROM pending_deletions", fetch_all=True) or []
        )

    def report_pending(self, logger: Optional[Any] = None) -> dict:
        """
        Logs all queued deletions and returns a JSON-ready summary for the frontend.
        """
        rows = self.list_pending()
        if not rows:
            if logger:
                logger.info("No pending deletions found.")
            return {
                "total": 0,
                "pending": [],
                "summary": {"by_type": {}, "by_year": {}, "by_season": {}},
            }

        header = ["ID", "Type", "Title", "Year", "Season", "File Path", "Date Queued"]
        if logger:
            logger.info(f"Pending deletions: {len(rows)} entries queued")
            logger.debug("Pending Deletions:")
            logger.debug(" | ".join(header))
            logger.debug("-" * 80)
            for row in rows:
                logger.debug(
                    f"{row['id']:>3} | {row['asset_type']:<8} | {row['title']:<40} | {str(row['year'] or ''):<6} | "
                    f"{str(row['season'] or ''):<6} | {row['file_path']:<60} | {row['date_queued']}"
                )

        pending = []
        by_type = {}
        by_year = {}
        by_season = {}
        for row in rows:
            pending.append(row)
            typ = row.get("asset_type", "unknown")
            by_type[typ] = by_type.get(typ, 0) + 1
            year = row.get("year") or "unknown"
            by_year[year] = by_year.get(year, 0) + 1
            season = row.get("season")
            if season is not None:
                by_season[season] = by_season.get(season, 0) + 1

        return {
            "total": len(pending),
            "pending": pending,
            "summary": {
                "by_type": by_type,
                "by_year": by_year,
                "by_season": by_season,
            },
        }

    def process_pending(
        self,
        logger: Optional[Any] = None,
        dry_run: bool = False,
        allowed_roots: Optional[List[str]] = None,
    ) -> None:
        """
        Deletes (or reports) queued posters from the file system and database.

        If `allowed_roots` is a non-empty list, any row whose `file_path` does not
        resolve to a location under one of those roots is treated as out-of-scope:
        the file is left on disk and the DB row is pruned so the stale record
        doesn't keep triggering the check. Without `allowed_roots` the legacy
        unscoped behavior applies.
        """
        rows = self.list_pending()
        if not rows:
            if logger:
                logger.info("No pending deletions found.")
            return

        scoped = bool(allowed_roots)

        header = ["ID", "Type", "Title", "Year", "Season", "File Path", "Date Queued"]
        if logger:
            logger.info(f"Pending deletions: {len(rows)} entries queued")
            logger.debug("Pending Deletions:")
            logger.debug(" | ".join(header))
            logger.debug("-" * 80)
            for row in rows:
                logger.debug(
                    f"{row['id']:>3} | {row['asset_type']:<8} | {row['title']:<40} | {str(row['year'] or ''):<6} | "
                    f"{str(row['season'] or ''):<6} | {row['file_path']:<60} | {row['date_queued']}"
                )

        deleted = 0
        kept = 0
        skipped_out_of_scope = 0

        operations = []
        for row in rows:
            file_path = row["file_path"]
            summary = f"[{row['asset_type']}] {row['title']} (year={row['year']} season={row['season']}) -> {file_path}"

            if dry_run:
                if logger:
                    logger.debug(f"[DRY RUN] Would delete: {summary}")
                kept += 1
                continue

            in_scope = (not scoped) or _path_under_any_root(file_path, allowed_roots)
            if not in_scope:
                if logger:
                    logger.warning(
                        f"[SKIPPED out-of-scope] Refusing to delete file outside configured roots: {summary}"
                    )
                skipped_out_of_scope += 1
                operations.append(
                    ("DELETE FROM pending_deletions WHERE id=?", (row["id"],))
                )
                continue

            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    if logger:
                        logger.debug(f"Deleted queued poster: {summary}")
                    deleted += 1
                else:
                    if logger:
                        logger.debug(f"File already missing: {summary}")
            except Exception as e:
                if logger:
                    logger.error(f"Failed to delete {file_path}: {e}")

            operations.append(
                ("DELETE FROM pending_deletions WHERE id=?", (row["id"],))
            )

        if operations:
            self.execute_transaction(operations)

        if logger:
            logger.info(
                f"Pending deletions handled: {deleted} deleted, "
                f"{skipped_out_of_scope} skipped (out of scope), "
                f"{kept} kept (dry run)"
            )

    def clear_pending(self) -> None:
        """Delete all rows from pending_deletions."""
        self.execute_query("DELETE FROM pending_deletions")
