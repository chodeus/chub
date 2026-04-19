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


class OrphanedPosters(DatabaseBase):
    """
    Handles querying and cleaning up orphaned posters.
    """

    def list_orphaned_posters(self) -> list:
        """Returns all orphaned posters as a list of dicts."""
        return (
            self.execute_query("SELECT * FROM orphaned_posters", fetch_all=True) or []
        )

    def report_orphaned_posters(self, logger: Optional[Any] = None) -> dict:
        """
        Logs all orphaned posters and returns a JSON-ready summary for the frontend.
        """
        rows = self.list_orphaned_posters()
        if not rows:
            if logger:
                logger.info("No orphaned posters found.")
            return {
                "total": 0,
                "orphaned": [],
                "summary": {"by_type": {}, "by_year": {}, "by_season": {}},
            }

        header = ["ID", "Type", "Title", "Year", "Season", "File Path", "Date Orphaned"]
        if logger:
            logger.info("Orphaned Posters:")
            logger.info(" | ".join(header))
            logger.info("-" * 80)
            for row in rows:
                logger.info(
                    f"{row['id']:>3} | {row['asset_type']:<8} | {row['title']:<40} | {str(row['year'] or ''):<6} | "
                    f"{str(row['season'] or ''):<6} | {row['file_path']:<60} | {row['date_orphaned']}"
                )
            logger.info("")

        orphaned = []
        by_type = {}
        by_year = {}
        by_season = {}
        for row in rows:
            orphaned.append(row)
            typ = row.get("asset_type", "unknown")
            by_type[typ] = by_type.get(typ, 0) + 1
            year = row.get("year") or "unknown"
            by_year[year] = by_year.get(year, 0) + 1
            season = row.get("season")
            if season is not None:
                by_season[season] = by_season.get(season, 0) + 1

        return {
            "total": len(orphaned),
            "orphaned": orphaned,
            "summary": {
                "by_type": by_type,
                "by_year": by_year,
                "by_season": by_season,
            },
        }

    def handle_orphaned_posters(
        self,
        logger: Optional[Any] = None,
        dry_run: bool = False,
        allowed_roots: Optional[List[str]] = None,
    ) -> None:
        """
        Deletes (or reports) orphaned posters from the file system and database.

        If `allowed_roots` is a non-empty list, any row whose `file_path` does not
        resolve to a location under one of those roots is treated as out-of-scope:
        the file is left on disk and the DB row is pruned so the stale record
        doesn't keep triggering the check. Without `allowed_roots` the legacy
        unscoped behavior applies.
        """
        rows = self.list_orphaned_posters()
        if not rows:
            if logger:
                logger.info("No orphaned posters found.")
            return

        scoped = bool(allowed_roots)

        header = ["ID", "Type", "Title", "Year", "Season", "File Path", "Date Orphaned"]
        if logger:
            logger.info("Orphaned Posters:")
            logger.info(" | ".join(header))
            logger.info("-" * 80)
            for row in rows:
                logger.info(
                    f"{row['id']:>3} | {row['asset_type']:<8} | {row['title']:<40} | {str(row['year'] or ''):<6} | "
                    f"{str(row['season'] or ''):<6} | {row['file_path']:<60} | {row['date_orphaned']}"
                )
            logger.info("")

        deleted = 0
        kept = 0
        skipped_out_of_scope = 0

        # Process each orphaned poster
        operations = []
        for row in rows:
            file_path = row["file_path"]
            summary = f"[{row['asset_type']}] {row['title']} (year={row['year']} season={row['season']}) -> {file_path}"

            if dry_run:
                if logger:
                    logger.info(f"[DRY RUN] Would delete: {summary}")
                kept += 1
                continue

            in_scope = (not scoped) or _path_under_any_root(file_path, allowed_roots)
            if not in_scope:
                if logger:
                    logger.warning(
                        f"[SKIPPED out-of-scope] Refusing to delete file outside configured roots: {summary}"
                    )
                skipped_out_of_scope += 1
                # Prune the stale record so it stops triggering on every run.
                operations.append(
                    ("DELETE FROM orphaned_posters WHERE id=?", (row["id"],))
                )
                continue

            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    if logger:
                        logger.info(f"Deleted orphaned poster: {summary}")
                    deleted += 1
                else:
                    if logger:
                        logger.info(f"File already missing: {summary}")
            except Exception as e:
                if logger:
                    logger.error(f"Failed to delete {file_path}: {e}")

            # Queue database deletion
            operations.append(
                ("DELETE FROM orphaned_posters WHERE id=?", (row["id"],))
            )

        # Execute all database deletions in a transaction
        if operations:
            self.execute_transaction(operations)

        if logger:
            logger.info(
                f"Orphaned posters handled: {deleted} deleted, "
                f"{skipped_out_of_scope} skipped (out of scope), "
                f"{kept} kept (dry run)"
            )

    def clear_orphaned_posters(self) -> None:
        """Delete all rows from orphaned_posters."""
        self.execute_query("DELETE FROM orphaned_posters")
