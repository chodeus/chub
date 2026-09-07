# util/database/maintenance.py

import sqlite3
from typing import Any, Dict, List, Set

from .db_base import DatabaseBase


class DbMaintenance(DatabaseBase):
    """Whole-file database operations: liveness, row counts, page stats, VACUUM.

    Everything here is about the SQLite file itself rather than any one table,
    so it has no natural home on a per-table cache interface.
    """

    # Explicit allowlist: the interpolated COUNT(*) may only name a fixed
    # literal, and internal SQLite tables stay hidden.
    STATS_TABLES = (
        "media_cache",
        "poster_cache",
        "collections_cache",
        "plex_media_cache",
        "jobs",
        "webhook_cache",
        "gdrive_stats",
        "scan_cache",
        "system_health_snapshots",
        "media_edit_history",
        "upgradinatorr_progress",
        "poster_collections",
        "poster_collection_items",
        "holiday_status",
        "run_state",
        "schema_migrations",
    )

    def ping(self) -> bool:
        """Round-trip the simplest possible query; raises if the DB is unusable."""
        self.execute_query("SELECT 1", fetch_one=True)
        return True

    def existing_tables(self) -> Set[str]:
        """Names of every table currently present in the schema."""
        rows = (
            self.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table'", fetch_all=True
            )
            or []
        )
        return {row["name"] for row in rows}

    def table_row_counts(self) -> List[Dict[str, Any]]:
        """Row count per STATS_TABLES entry, skipping tables not in this schema."""
        existing = self.existing_tables()
        counts = []
        for name in self.STATS_TABLES:
            if name not in existing:
                continue
            # name comes from the STATS_TABLES literal tuple, never from a caller.
            row = self.execute_query(
                f"SELECT COUNT(*) AS total FROM {name}",  # noqa: S608
                fetch_one=True,
            )
            counts.append({"name": name, "rows": row["total"] if row else 0})
        return counts

    def page_stats(self) -> Dict[str, int]:
        """SQLite page/freelist counters plus the byte totals derived from them."""
        page_size_row = self.execute_query("PRAGMA page_size", fetch_one=True)
        page_count_row = self.execute_query("PRAGMA page_count", fetch_one=True)
        freelist_row = self.execute_query("PRAGMA freelist_count", fetch_one=True)
        page_size = int(page_size_row["page_size"]) if page_size_row else 0
        page_count = int(page_count_row["page_count"]) if page_count_row else 0
        freelist_count = int(freelist_row["freelist_count"]) if freelist_row else 0
        return {
            "page_size": page_size,
            "page_count": page_count,
            "freelist_count": freelist_count,
            "total_bytes": page_size * page_count,
            "free_bytes": page_size * freelist_count,
        }

    def list_migrations(self) -> List[Dict[str, Any]]:
        """Applied schema migrations, newest first; empty when the table is absent."""
        if "schema_migrations" not in self.existing_tables():
            return []
        return (
            self.execute_query(
                "SELECT name, applied_at FROM schema_migrations "
                "ORDER BY applied_at DESC, name DESC",
                fetch_all=True,
            )
            or []
        )

    def vacuum(self) -> None:
        """Compact the database file (SQLite VACUUM)."""
        # Bypasses get_connection: VACUUM can't run inside a transaction.
        conn = sqlite3.connect(self.db_path, timeout=60)
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
        finally:
            conn.close()
