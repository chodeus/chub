import os
from collections import defaultdict
from typing import Any, Dict

from .db_base import DatabaseBase


class Stats(DatabaseBase):
    """
    Methods for fetching statistical/summary data about posters, collections, and other media.
    """

    def get_poster_source_stats(self) -> list:
        """
        Returns all poster source stats as a list of dicts.
        """
        return (
            self.execute_query("SELECT * FROM poster_source_stats", fetch_all=True)
            or []
        )

    def get_unmatched_assets_stats(self) -> Dict[str, Any]:
        """
        Returns a summary dict with unmatched media, unmatched collections, and totals.
        """
        unmatched_media = (
            self.execute_query(
                "SELECT * FROM media_cache WHERE matched=0", fetch_all=True
            )
            or []
        )

        unmatched_collections = (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE matched=0", fetch_all=True
            )
            or []
        )

        all_media = (
            self.execute_query("SELECT * FROM media_cache", fetch_all=True) or []
        )

        all_collections = (
            self.execute_query("SELECT * FROM collections_cache", fetch_all=True) or []
        )

        return {
            "unmatched": unmatched_media,
            "unmatched_collections": unmatched_collections,
            "all_media": all_media,
            "all_collections": all_collections,
            "summary": {
                "unmatched_count": len(unmatched_media),
                "unmatched_collections_count": len(unmatched_collections),
                "total_media_count": len(all_media),
                "total_collections_count": len(all_collections),
            },
        }

    def count_poster_cache(self) -> int:
        """
        Returns the total number of records in the poster_cache table.
        """
        result = self.execute_query(
            "SELECT COUNT(*) as cnt FROM poster_cache", fetch_one=True
        )
        return result["cnt"] if result else 0

    def get_applied_breakdowns(self) -> Dict[str, Dict[str, int]]:
        """Breakdowns of posters actually applied to the library (matched rows),
        NOT the full GDrive catalog.

        Applied posters live at ``.../<STYLE>/<source>/<file>``, so style is the
        grandparent directory and source is the parent directory of
        original_file. Returns counts ``by_style``, ``by_type``, and
        ``by_source``.
        """
        media = (
            self.execute_query(
                "SELECT original_file, asset_type, season_number FROM media_cache "
                "WHERE matched=1 AND original_file IS NOT NULL AND original_file != ''",
                fetch_all=True,
            )
            or []
        )
        collections = (
            self.execute_query(
                "SELECT original_file FROM collections_cache "
                "WHERE matched=1 AND original_file IS NOT NULL AND original_file != ''",
                fetch_all=True,
            )
            or []
        )

        by_style: Dict[str, int] = defaultdict(int)
        by_type: Dict[str, int] = defaultdict(int)
        by_source: Dict[str, int] = defaultdict(int)

        def attribute_path(path: str) -> None:
            by_style[os.path.basename(os.path.dirname(os.path.dirname(path))) or "other"] += 1
            by_source[os.path.basename(os.path.dirname(path)) or "other"] += 1

        for row in media:
            attribute_path(row["original_file"])
            asset_type = row["asset_type"] or "other"
            if asset_type == "show" and row["season_number"] is not None:
                asset_type = "season"
            by_type[asset_type] += 1

        for row in collections:
            attribute_path(row["original_file"])
            by_type["collection"] += 1

        return {
            "by_style": dict(by_style),
            "by_type": dict(by_type),
            "by_source": dict(by_source),
        }

    def get_applied_media_by_style(
        self, style, asset_type=None, limit=100, offset=0
    ) -> Dict[str, Any]:
        """List matched media whose applied poster is of the given style variant.

        Lets a user drill into a variant (e.g. CL2K) to see which titles use it
        and request the other variant. ``asset_type`` optionally narrows to
        movie/show/season. Returns ``{items, total}`` sorted by title.
        """
        rows = (
            self.execute_query(
                "SELECT id, title, year, asset_type, season_number, tmdb_id, "
                "tvdb_id, imdb_id, instance_name, original_file FROM media_cache "
                "WHERE matched=1 AND original_file IS NOT NULL AND original_file != ''",
                fetch_all=True,
            )
            or []
        )

        def style_of(path: str) -> str:
            return os.path.basename(os.path.dirname(os.path.dirname(path))) or "other"

        def type_of(row) -> str:
            atype = row["asset_type"] or "other"
            if atype == "show" and row["season_number"] is not None:
                return "season"
            return atype

        matches = [r for r in rows if style_of(r["original_file"]) == style]
        if asset_type:
            matches = [r for r in matches if type_of(r) == asset_type]
        matches.sort(key=lambda r: (r["title"] or "").lower())

        total = len(matches)
        page = matches[offset : offset + limit]
        items = []
        for r in page:
            item = dict(r)
            item["resolved_type"] = type_of(r)
            items.append(item)
        return {"items": items, "total": total}

    def upsert_gdrive_stat(
        self, location, folder_name, owner, file_count, size_bytes, last_updated
    ):
        """
        Upsert (insert or update) a GDrive stat record for the given location.
        """
        self.execute_query(
            """
            INSERT INTO gdrive_stats (location, folder_name, owner, file_count, size_bytes, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(location) DO UPDATE SET
                folder_name=excluded.folder_name,
                owner=excluded.owner,
                file_count=excluded.file_count,
                size_bytes=excluded.size_bytes,
                last_updated=excluded.last_updated
            """,
            (location, folder_name, owner, file_count, size_bytes, last_updated),
        )

    def get_gdrive_stats(self) -> list:
        """
        Returns all GDrive stats as a list of dicts.
        """
        return self.execute_query("SELECT * FROM gdrive_stats", fetch_all=True) or []

    def get_matched_posters_stats(self):
        """Get statistics about matched posters by owner."""
        # Fetch media records
        media = (
            self.execute_query(
                "SELECT matched, original_file FROM media_cache WHERE original_file IS NOT NULL AND original_file != ''",
                fetch_all=True,
            )
            or []
        )

        # Fetch collection records
        collections = (
            self.execute_query(
                "SELECT matched, original_file FROM collections_cache WHERE original_file IS NOT NULL AND original_file != ''",
                fetch_all=True,
            )
            or []
        )

        owner_stats = defaultdict(
            lambda: {
                "media_matched": 0,
                "media_total": 0,
                "collections_matched": 0,
                "collections_total": 0,
            }
        )

        # Aggregate media
        for row in media:
            owner = os.path.basename(os.path.dirname(row["original_file"])) or "unknown"
            owner_stats[owner]["media_total"] += 1
            if row["matched"]:
                owner_stats[owner]["media_matched"] += 1

        # Aggregate collections
        for row in collections:
            owner = os.path.basename(os.path.dirname(row["original_file"])) or "unknown"
            owner_stats[owner]["collections_total"] += 1
            if row["matched"]:
                owner_stats[owner]["collections_matched"] += 1

        # Calculate percentages
        results = []
        for owner, stats in sorted(owner_stats.items()):
            media_pct = (
                round((stats["media_matched"] / stats["media_total"] * 100), 1)
                if stats["media_total"]
                else 0
            )
            collections_pct = (
                round(
                    (stats["collections_matched"] / stats["collections_total"] * 100), 1
                )
                if stats["collections_total"]
                else 0
            )
            overall_matched = stats["media_matched"] + stats["collections_matched"]
            overall_total = stats["media_total"] + stats["collections_total"]
            overall_pct = (
                round((overall_matched / overall_total * 100), 1)
                if overall_total
                else 0
            )
            results.append(
                {
                    "owner": owner,
                    "media_matched": stats["media_matched"],
                    "media_total": stats["media_total"],
                    "media_pct": media_pct,
                    "collections_matched": stats["collections_matched"],
                    "collections_total": stats["collections_total"],
                    "collections_pct": collections_pct,
                    "overall_matched": overall_matched,
                    "overall_total": overall_total,
                    "overall_pct": overall_pct,
                }
            )

        return results
