"""Library-health statistics over media_cache, mixed into MediaCache."""

import json
from typing import Optional

from .db_base import DatabaseBase

# Library-health SQL fragments, shared across the stats queries so by_type,
# totals and by_instance can't drift. Everything is counted in CONTENT UNITS —
# a movie, an album, or a single TV episode — to match each *arr's native unit:
#   units      = total content units
#   in_library = units whose file is present
#   missing    = monitored units that are released/aired but have no file
#   upcoming   = monitored units not yet released/aired
# A Sonarr SEASON row expands to its episode counts; a movie/album is 1 unit;
# shows, seasons-as-rows... no — shows and artists are CONTAINERS (0 units; the
# episodes/albums carry the counts), so they fall through to 0 automatically.
# "released" gates simple (movie/album) units: Lidarr albums use their own
# release_date (absent = released), movies/shows use the *arr `status` (mirrors
# release_readiness.UNRELEASED_STATUSES). For seasons, "aired" IS the gate:
# missing = aired-on-disk shortfall, upcoming = not-yet-aired.
_RELEASED_SQL = (
    "CASE WHEN asset_type='album' "
    "THEN (release_date IS NULL OR release_date <= date('now')) "
    "ELSE (status IS NULL OR status NOT IN "
    "('announced','deleted','tba','upcoming')) END"
)
_IS_SEASON = "(asset_type='show' AND season_number IS NOT NULL)"
_IS_SIMPLE = "asset_type IN ('movie','album')"  # 1-unit content types

_UNITS_TOTAL_SQL = (
    f"SUM(CASE WHEN {_IS_SEASON} THEN COALESCE(total_episodes,0) "
    f"WHEN {_IS_SIMPLE} THEN 1 ELSE 0 END)"
)
# An album under an UNMONITORED artist isn't "wanted" — Lidarr's Wanted page
# excludes it, so missing/upcoming do too. NULL (pre-column rows) = monitored.
_ALBUM_ARTIST_OK = "(asset_type != 'album' OR COALESCE(artist_monitored, 1) = 1)"
_IN_LIBRARY_SQL = (
    f"SUM(CASE WHEN {_IS_SEASON} THEN COALESCE(episode_files,0) "
    f"WHEN {_IS_SIMPLE} AND has_content=1 THEN 1 ELSE 0 END)"
)
_MISSING_SQL = (
    f"SUM(CASE WHEN {_IS_SEASON} AND monitored=1 "
    "THEN MAX(0, COALESCE(aired_episodes,0) - COALESCE(episode_files,0)) "
    f"WHEN {_IS_SIMPLE} AND monitored=1 AND COALESCE(has_content,0)=0 "
    f"AND {_RELEASED_SQL} AND {_ALBUM_ARTIST_OK} THEN 1 ELSE 0 END)"
)
_UPCOMING_SQL = (
    f"SUM(CASE WHEN {_IS_SEASON} AND monitored=1 "
    "THEN MAX(0, COALESCE(total_episodes,0) - COALESCE(aired_episodes,0)) "
    f"WHEN {_IS_SIMPLE} AND monitored=1 AND COALESCE(has_content,0)=0 "
    f"AND NOT ({_RELEASED_SQL}) AND {_ALBUM_ARTIST_OK} THEN 1 ELSE 0 END)"
)
# Row-count fragments (containers): for the artist/show context cards.
_MONITORED_SQL = "SUM(CASE WHEN monitored=1 THEN 1 ELSE 0 END)"
_SHOW_COUNT_SQL = (
    "SUM(CASE WHEN asset_type='show' AND season_number IS NULL THEN 1 ELSE 0 END)"
)
_MONITORED_SHOWS_SQL = (
    "SUM(CASE WHEN asset_type='show' AND season_number IS NULL AND monitored=1 "
    "THEN 1 ELSE 0 END)"
)
_SEASON_COUNT_SQL = (
    "SUM(CASE WHEN asset_type='show' AND season_number IS NOT NULL THEN 1 ELSE 0 END)"
)
_ARTIST_COUNT_SQL = "SUM(CASE WHEN asset_type='artist' THEN 1 ELSE 0 END)"
_MONITORED_ARTISTS_SQL = (
    "SUM(CASE WHEN asset_type='artist' AND monitored=1 THEN 1 ELSE 0 END)"
)


class StatsMixin(DatabaseBase):
    """Aggregate library-health statistics over the media_cache table."""

    def count_added_since(self, cutoff: str) -> int:
        """Rows first seen at or after an ISO cutoff (created_at is first-insert)."""
        row = self.execute_query(
            "SELECT COUNT(*) AS total FROM media_cache WHERE created_at >= ?",
            (cutoff,),
            fetch_one=True,
        )
        return int(row["total"]) if row else 0

    def count_unmatched(self) -> int:
        """Rows with no poster match — the Unmatched page's media figure."""
        row = self.execute_query(
            "SELECT COUNT(*) AS total FROM media_cache WHERE matched=0",
            fetch_one=True,
        )
        return int(row["total"]) if row else 0

    def get_stats(
        self, asset_type: Optional[str] = None, period_days: int = None
    ) -> dict:
        """Aggregate statistics from media_cache."""
        conditions = []
        params: list = []
        if asset_type and asset_type != "all":
            conditions.append("asset_type = ?")
            params.append(asset_type)
        if period_days:
            conditions.append("created_at >= datetime('now', ?)")
            params.append(f"-{period_days} days")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params = tuple(params)

        # Library-health metrics — see the module-level _*_SQL fragments.
        rows = (
            self.execute_query(
                f"""
                SELECT asset_type,
                       COUNT(*) as total,
                       {_UNITS_TOTAL_SQL} as units,
                       {_IN_LIBRARY_SQL} as in_library,
                       {_MISSING_SQL} as missing,
                       {_UPCOMING_SQL} as upcoming,
                       {_MONITORED_SQL} as monitored,
                       {_SHOW_COUNT_SQL} as show_count,
                       {_MONITORED_SHOWS_SQL} as monitored_shows,
                       {_SEASON_COUNT_SQL} as season_count,
                       COUNT(DISTINCT instance_name) as instances
                FROM media_cache {where}
                GROUP BY asset_type
                """,
                params,
                fetch_all=True,
            )
            or []
        )

        totals = self.execute_query(
            f"""
            SELECT {_UNITS_TOTAL_SQL} as total,
                   {_IN_LIBRARY_SQL} as in_library,
                   {_MISSING_SQL} as missing,
                   {_UPCOMING_SQL} as upcoming,
                   {_MONITORED_SQL} as monitored
            FROM media_cache {where}
            """,
            params,
            fetch_one=True,
        )

        return {
            "by_type": rows,
            # Headline numbers are in content units (movies + episodes + albums).
            "total": (totals["total"] or 0) if totals else 0,
            "in_library": (totals["in_library"] or 0) if totals else 0,
            "missing": (totals["missing"] or 0) if totals else 0,
            "upcoming": (totals["upcoming"] or 0) if totals else 0,
            "monitored": (totals["monitored"] or 0) if totals else 0,
        }

    def get_detailed_stats(
        self, asset_type: Optional[str] = None, period_days: int = None
    ) -> dict:
        """Extended statistics with breakdowns by multiple dimensions."""
        conditions = []
        params_list: list = []
        if asset_type and asset_type != "all":
            conditions.append("asset_type = ?")
            params_list.append(asset_type)
        if period_days:
            conditions.append("created_at >= datetime('now', ?)")
            params_list.append(f"-{period_days} days")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params = tuple(params_list)

        # Base stats (same as get_stats)
        base = self.get_stats(asset_type=asset_type, period_days=period_days)

        # By instance (source = service type: radarr/sonarr/lidarr/plex)
        by_instance = (
            self.execute_query(
                f"""SELECT instance_name, source, COUNT(*) as total,
                       {_UNITS_TOTAL_SQL} as units,
                       {_IN_LIBRARY_SQL} as in_library,
                       {_MISSING_SQL} as missing,
                       {_UPCOMING_SQL} as upcoming,
                       {_MONITORED_SQL} as monitored,
                       {_SHOW_COUNT_SQL} as show_count,
                       {_MONITORED_SHOWS_SQL} as monitored_shows,
                       {_SEASON_COUNT_SQL} as season_count,
                       {_ARTIST_COUNT_SQL} as artist_count,
                       {_MONITORED_ARTISTS_SQL} as monitored_artists
                FROM media_cache {where}
                GROUP BY instance_name, source ORDER BY total DESC""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By status
        by_status = (
            self.execute_query(
                f"""SELECT status, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} status IS NOT NULL AND status != ''
                GROUP BY status ORDER BY count DESC""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By language
        by_language = (
            self.execute_query(
                f"""SELECT language, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} language IS NOT NULL AND language != ''
                GROUP BY language ORDER BY count DESC""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By rating (content ratings like PG, R, TV-MA)
        by_rating = (
            self.execute_query(
                f"""SELECT rating, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} rating IS NOT NULL AND rating != ''
                GROUP BY rating ORDER BY count DESC""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By studio (top 50)
        by_studio = (
            self.execute_query(
                f"""SELECT studio, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} studio IS NOT NULL AND studio != ''
                GROUP BY studio ORDER BY count DESC LIMIT 50""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By year/decade
        by_decade = (
            self.execute_query(
                f"""SELECT (CAST(year AS INTEGER) / 10) * 10 as decade, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} year IS NOT NULL AND year != ''
                GROUP BY decade ORDER BY decade DESC""",
                params,
                fetch_all=True,
            )
            or []
        )
        by_decade = [
            {"decade": f"{r['decade']}s", "count": r["count"]}
            for r in by_decade
            if r.get("decade")
        ]

        # By runtime buckets
        by_runtime = (
            self.execute_query(
                f"""SELECT
                    CASE
                        WHEN CAST(runtime AS INTEGER) < 30 THEN 'Under 30m'
                        WHEN CAST(runtime AS INTEGER) < 60 THEN '30-60m'
                        WHEN CAST(runtime AS INTEGER) < 90 THEN '60-90m'
                        WHEN CAST(runtime AS INTEGER) < 120 THEN '90-120m'
                        WHEN CAST(runtime AS INTEGER) < 150 THEN '120-150m'
                        ELSE '150m+'
                    END as bucket,
                    COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} runtime IS NOT NULL AND runtime != '' AND CAST(runtime AS INTEGER) > 0
                GROUP BY bucket ORDER BY MIN(CAST(runtime AS INTEGER))""",
                params,
                fetch_all=True,
            )
            or []
        )

        # Monitored counts
        mon_row = self.execute_query(
            f"""SELECT
                    SUM(CASE WHEN monitored = 1 THEN 1 ELSE 0 END) as monitored,
                    SUM(CASE WHEN monitored = 0 THEN 1 ELSE 0 END) as unmonitored
                FROM media_cache {where}""",
            params,
            fetch_one=True,
        )
        monitored = {
            "monitored": mon_row["monitored"] or 0 if mon_row else 0,
            "unmonitored": mon_row["unmonitored"] or 0 if mon_row else 0,
        }

        # By genre (Python-side aggregation since genre is JSON array)
        genre_rows = (
            self.execute_query(
                f"SELECT genre FROM media_cache {where + (' AND' if where else 'WHERE')} genre IS NOT NULL AND genre != ''",
                params,
                fetch_all=True,
            )
            or []
        )
        genre_counts: dict = {}
        for row in genre_rows:
            raw = row.get("genre", "")
            if not raw:
                continue
            parsed_genres = []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    parsed_genres = [str(g).strip() for g in parsed if g]
            except (json.JSONDecodeError, TypeError):
                parsed_genres = [g.strip() for g in raw.split(",") if g.strip()]
            for g in parsed_genres:
                genre_counts[g] = genre_counts.get(g, 0) + 1
        by_genre = sorted(
            [{"genre": k, "count": v} for k, v in genre_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        # By root folder (where media lives on disk — *arr only; Plex has none)
        by_root_folder = (
            self.execute_query(
                f"""SELECT root_folder, COUNT(*) as count
                FROM media_cache {where + (" AND" if where else "WHERE")} root_folder IS NOT NULL AND root_folder != ''
                GROUP BY root_folder ORDER BY count DESC""",
                params,
                fetch_all=True,
            )
            or []
        )

        # By tag (Python-side aggregation since tags is a JSON array of names)
        tag_rows = (
            self.execute_query(
                f"SELECT tags FROM media_cache {where + (' AND' if where else 'WHERE')} tags IS NOT NULL AND tags != '' AND tags != '[]'",
                params,
                fetch_all=True,
            )
            or []
        )
        tag_counts: dict = {}
        for row in tag_rows:
            raw = row.get("tags", "")
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                tags = (
                    [str(t).strip() for t in parsed if t]
                    if isinstance(parsed, list)
                    else []
                )
            except (json.JSONDecodeError, TypeError):
                tags = [t.strip() for t in raw.split(",") if t.strip()]
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        by_tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )

        recently_added = self.get_recently_added(asset_type=asset_type)

        return {
            **base,
            "by_instance": by_instance,
            "recently_added": recently_added,
            "by_root_folder": by_root_folder,
            "by_tags": by_tags,
            "by_status": by_status,
            "by_language": by_language,
            "by_rating": by_rating,
            "by_studio": by_studio,
            "by_decade": by_decade,
            "by_runtime": by_runtime,
            "by_genre": by_genre,
            "monitored": monitored,
        }

    def get_recently_added(
        self, asset_type: Optional[str] = None, limit: int = 12
    ) -> dict:
        """Most recently added library items, keyed on ``created_at`` (stamped
        once on first insert = first-seen time).

        Rows that predate created_at stamping carry NULL and never appear here,
        so this reflects genuinely new additions going forward — it is not a
        backfill of the existing library. Per-item ``added_age_seconds`` uses
        SQLite's clock (matching the snapshot-age fields) so the frontend never
        has to parse a bare timestamp.
        """
        conditions = ["created_at IS NOT NULL"]
        params: list = []
        if asset_type and asset_type != "all":
            conditions.append("asset_type = ?")
            params.append(asset_type)
        where = "WHERE " + " AND ".join(conditions)

        def _count(days: int) -> int:
            row = self.execute_query(
                f"SELECT COUNT(*) AS n FROM media_cache {where} "
                "AND created_at >= datetime('now', ?)",
                tuple(params + [f"-{days} days"]),
                fetch_one=True,
            )
            return (row["n"] or 0) if row else 0

        items = (
            self.execute_query(
                f"""SELECT title, asset_type, instance_name, source, year,
                       CAST(strftime('%s','now') - strftime('%s', created_at) AS REAL)
                           AS added_age_seconds
                FROM media_cache {where}
                ORDER BY created_at DESC LIMIT ?""",
                tuple(params + [limit]),
                fetch_all=True,
            )
            or []
        )

        return {
            "last_7d": _count(7),
            "last_30d": _count(30),
            "items": items,
        }
