import json
from typing import Optional

from backend.util.normalization import normalize_titles

from .db_base import DatabaseBase


# ─────────────────────────────────────────────────────────────────────
# CONTRACT: source_dirs bottom-wins priority
# ─────────────────────────────────────────────────────────────────────
# When two source_dirs both contain a poster for the same media item,
# the entry from the **bottom** of poster_renamerr.source_dirs must win.
# This matches the user-facing tooltip in
# frontend/src/utils/constants/settings_schema.js and gives DAPS parity.
#
# Mechanism:
#   1. PosterRenamerr.merge_assets stamps each asset's `priority` to the
#      0-based index of its source_dir in config.source_dirs (top=0,
#      bottom=N-1). Higher value = later in list = wins.
#   2. The match-phase queries below (`get_by_id`,
#      `get_by_normalized_title`, `get_candidates_by_prefix`) ORDER BY
#      `priority DESC, id DESC` so the bottom source_dir's row is
#      returned first. `id DESC` is the within-same-priority tiebreaker
#      (later-inserted file wins).
#   3. SyncGDrive._refresh_poster_cache_for_folder looks up the priority
#      for the folder being refreshed so per-folder syncs preserve it.
#
# Guardrail: tests/test_poster_renamerr.py::test_source_dirs_bottom_wins.
# Removing the ORDER BY clauses, the priority column, or the priority
# stamping in merge_assets will fail that test loudly. Do not "simplify"
# this without reading the test first — the ordering is the contract.
# ─────────────────────────────────────────────────────────────────────


class PosterCache(DatabaseBase):
    """
    Handles CRUD operations and logic for the poster_cache table.
    """

    @staticmethod
    def _canonical_key(item: dict) -> tuple:
        """Returns a tuple key matching the UNIQUE constraint on poster_cache."""

        def norm_int(val):
            if val in (None, "", "None"):
                return None
            try:
                return int(val)
            except Exception:
                return None

        def norm_str(val):
            if val in (None, "", "None"):
                return None
            return str(val).strip() if isinstance(val, str) else val

        return (
            norm_str(item.get("title")),
            norm_int(item.get("year")),
            norm_int(item.get("tmdb_id")),
            norm_int(item.get("tvdb_id")),
            norm_str(item.get("imdb_id")),
            norm_int(item.get("season_number")),
            norm_str(item.get("file")),
        )

    def upsert(self, record: dict) -> None:
        """Insert or update a record in poster_cache table."""
        # Serialize list/dict fields to JSON
        for key in ("alternate_titles", "normalized_alternate_titles"):
            if isinstance(record.get(key), (list, dict)):
                record[key] = json.dumps(record[key])
            elif record.get(key) is None:
                record[key] = json.dumps([])

        # created_at is set once on first insert and preserved on conflict
        # updates so it represents when the poster was first seen.
        from datetime import datetime, timezone

        created_at = record.get("created_at") or datetime.now(timezone.utc).isoformat()

        # priority: see CONTRACT block at top of file. Stamped by callers
        # from source_dir index; defaults to 0 if absent so direct DB
        # writes (tests, manual fixtures) don't have to know about it.
        priority = int(record.get("priority") or 0)

        self.execute_query(
            """
            INSERT INTO poster_cache
                (asset_type, title, normalized_title, year,
                 tmdb_id, tvdb_id, imdb_id, season_number, folder, file, style, created_at, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title, year, tmdb_id, tvdb_id, imdb_id, season_number, file)
            DO UPDATE SET
                asset_type=excluded.asset_type,
                normalized_title=excluded.normalized_title,
                folder=excluded.folder,
                style=excluded.style,
                priority=excluded.priority
            """,
            (
                record.get("asset_type"),
                record["title"],
                record["normalized_title"],
                record["year"],
                record["tmdb_id"],
                record["tvdb_id"],
                record["imdb_id"],
                record["season_number"],
                record["folder"],
                record["file"],
                record.get("style"),
                created_at,
                priority,
            ),
        )

    def record_dimensions(self, poster_id: int, width: int, height: int) -> None:
        """Persist width/height for a poster row (populated lazily by the API)."""
        self.execute_query(
            "UPDATE poster_cache SET width=?, height=? WHERE id=?",
            (int(width), int(height), int(poster_id)),
        )

    def find_low_resolution(self, min_width: int = 1000, limit: int = 200) -> list:
        """
        Return posters whose stored width falls below `min_width`. Rows
        with no recorded width are excluded — use record_dimensions first.
        """
        rows = (
            self.execute_query(
                "SELECT * FROM poster_cache WHERE width IS NOT NULL AND width < ? "
                "ORDER BY width ASC LIMIT ?",
                (int(min_width), int(limit)),
                fetch_all=True,
            )
            or []
        )
        return [dict(r) for r in rows]

    def added_since(self, iso_cutoff: str, limit: int = 500) -> list:
        """Return poster_cache rows added at or after the ISO-8601 cutoff."""
        rows = (
            self.execute_query(
                "SELECT * FROM poster_cache WHERE created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (iso_cutoff, int(limit)),
                fetch_all=True,
            )
            or []
        )
        return [dict(r) for r in rows]

    def get_all(self) -> list:
        """Return all records from poster_cache as a list of dicts."""
        return self.execute_query("SELECT * FROM poster_cache", fetch_all=True) or []

    def get_by_id(
        self,
        id_field: str,
        id_val,
        season_number=None,
        asset_type: Optional[str] = None,
    ) -> Optional[dict]:
        """Get poster cache record by ID field.

        Ordering enforces the bottom-wins source_dir contract — see
        CONTRACT block at top of file.
        """
        sql = f"SELECT * FROM poster_cache WHERE {id_field}=?"
        params = [id_val]

        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        if season_number is not None:
            sql += " AND season_number=?"
            params.append(season_number)
        else:
            sql += " AND season_number IS NULL"

        sql += " ORDER BY priority DESC, id DESC LIMIT 1"
        return self.execute_query(sql, params, fetch_one=True)

    def get_by_normalized_title(
        self,
        normalized_title: str,
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        asset_type: Optional[str] = None,
    ) -> Optional[dict]:
        """Get poster cache record by normalized title.

        Ordering enforces the bottom-wins source_dir contract — see
        CONTRACT block at top of file.
        """
        sql = "SELECT * FROM poster_cache WHERE normalized_title=?"
        params = [normalized_title]

        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        if year is not None:
            sql += " AND year=?"
            params.append(year)

        if season_number is not None:
            sql += " AND season_number=?"
            params.append(season_number)
        else:
            sql += " AND season_number IS NULL"

        sql += " ORDER BY priority DESC, id DESC LIMIT 1"
        return self.execute_query(sql, params, fetch_one=True)

    def clear(self) -> None:
        """Delete all rows from poster_cache."""
        self.execute_query("DELETE FROM poster_cache")

    def delete_by_path_prefix(self, path_prefix: str) -> int:
        """Delete all rows whose `file` path lives under `path_prefix`.

        Used to refresh a single source-dir's slice of the cache (e.g. after
        a per-folder gdrive sync) without touching unrelated rows. Matches
        on the absolute path so two contributor folders that happen to share
        a leaf name can't accidentally clobber each other.
        """
        prefix = path_prefix.rstrip("/") + "/"
        return self.execute_query(
            "DELETE FROM poster_cache WHERE file LIKE ?", (prefix + "%",)
        )

    def get_by_integer_id(self, poster_id: int) -> Optional[dict]:
        """Return a single poster_cache row by its integer primary key."""
        return self.execute_query(
            "SELECT * FROM poster_cache WHERE id=?", (poster_id,), fetch_one=True
        )

    def delete_by_integer_id(self, poster_id: int) -> Optional[dict]:
        """Delete a poster_cache record by integer ID. Returns the deleted record."""
        record = self.get_by_integer_id(poster_id)
        if record:
            self.execute_query("DELETE FROM poster_cache WHERE id=?", (poster_id,))
        return record

    def search(
        self, query: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> dict:
        """Search poster_cache by normalized title with pagination."""
        conditions = []
        params: list = []

        if query:
            # Match the same normalization that built the `normalized_title`
            # column so hyphenated / special-char searches ("x-men") still
            # find rows where the stored value collapsed to "xmen". Fall back
            # to a raw `title LIKE` so exact stored substrings still hit too.
            conditions.append("(normalized_title LIKE ? OR title LIKE ?)")
            params.extend([f"%{normalize_titles(query)}%", f"%{query}%"])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_result = self.execute_query(
            f"SELECT COUNT(*) as total FROM poster_cache {where}",
            tuple(params),
            fetch_one=True,
        )
        total = count_result["total"] if count_result else 0

        data_params = list(params) + [limit, offset]
        items = (
            self.execute_query(
                f"SELECT * FROM poster_cache {where} ORDER BY normalized_title ASC LIMIT ? OFFSET ?",
                tuple(data_params),
                fetch_all=True,
            )
            or []
        )

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_all_grouped(self) -> dict:
        """Return all poster_cache records grouped by type."""
        all_records = self.get_all()
        grouped = {"movies": [], "shows": [], "seasons": [], "collections": []}
        for record in all_records:
            asset_type = record.get("asset_type")
            season = record.get("season_number")
            if asset_type == "collection":
                grouped["collections"].append(record)
            elif asset_type == "movie":
                grouped["movies"].append(record)
            elif asset_type == "show" and season is not None:
                grouped["seasons"].append(record)
            elif asset_type == "show":
                grouped["shows"].append(record)
            elif season is not None:
                grouped["seasons"].append(record)
            else:
                grouped["shows"].append(record)
        return grouped

    def get_distinct_owners(self) -> list:
        """Return distinct owner names derived from the folder path."""
        rows = (
            self.execute_query(
                "SELECT DISTINCT folder FROM poster_cache WHERE folder IS NOT NULL AND folder != ''",
                fetch_all=True,
            )
            or []
        )
        owners = set()
        for row in rows:
            parts = row["folder"].rstrip("/").split("/")
            if parts:
                owners.add(parts[-1])
        return sorted(owners)

    def get_distinct_styles(self) -> list:
        """Return distinct non-empty style values stored on poster_cache rows."""
        rows = (
            self.execute_query(
                "SELECT DISTINCT style FROM poster_cache WHERE style IS NOT NULL AND style != ''",
                fetch_all=True,
            )
            or []
        )
        return sorted({row["style"] for row in rows if row.get("style")})

    def browse(
        self,
        owner: Optional[str] = None,
        asset_type: Optional[str] = None,
        query: Optional[str] = None,
        style: Optional[str] = None,
        limit: int = 60,
        offset: int = 0,
    ) -> dict:
        """Browse poster_cache with optional owner, type, style, and search filters."""
        conditions = []
        params: list = []

        if query:
            # Match the same normalization that built the `normalized_title`
            # column so hyphenated / special-char searches ("x-men") still
            # find rows where the stored value collapsed to "xmen". Fall back
            # to a raw `title LIKE` so exact stored substrings still hit too.
            conditions.append("(normalized_title LIKE ? OR title LIKE ?)")
            params.extend([f"%{normalize_titles(query)}%", f"%{query}%"])

        if owner:
            conditions.append("(folder = ? OR folder LIKE ?)")
            params.extend([owner, f"%/{owner}"])

        if asset_type in {"movie", "show", "collection"}:
            conditions.append("asset_type = ?")
            params.append(asset_type)
            if asset_type == "show":
                conditions.append("season_number IS NULL")
        elif asset_type == "season":
            conditions.append("asset_type = ?")
            params.append("show")
            conditions.append("season_number IS NOT NULL")

        # "other" matches rows whose source dir didn't resolve to a known
        # gdrive_list entry (style IS NULL).
        if style == "other":
            conditions.append("style IS NULL")
        elif style:
            conditions.append("style = ?")
            params.append(style)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_result = self.execute_query(
            f"SELECT COUNT(*) as total FROM poster_cache {where}",
            tuple(params),
            fetch_one=True,
        )
        total = count_result["total"] if count_result else 0

        data_params = list(params) + [limit, offset]
        items = (
            self.execute_query(
                f"SELECT * FROM poster_cache {where} ORDER BY normalized_title ASC LIMIT ? OFFSET ?",
                tuple(data_params),
                fetch_all=True,
            )
            or []
        )

        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get_candidates_by_prefix(
        self, title: str, length: int = 3, asset_type: Optional[str] = None
    ) -> list:
        """Get poster candidates by title prefix.

        Ordering enforces the bottom-wins source_dir contract — see
        CONTRACT block at top of file. The match phase walks this list
        and takes the first row that passes is_match(), so higher-
        priority candidates must come first.

        The prefix is derived with normalize_titles() — the SAME function that
        produced the stored `normalized_title` column — so they stay
        consistent. (get_prefix() strips leading articles, so "The Lovers"
        became prefix "lov" which never matched the stored "thelovers" — every
        no-id, article-prefixed title, e.g. season posters, silently failed to
        match.)
        """
        prefix = normalize_titles(title)[:length]
        if not prefix:
            return []

        sql = "SELECT * FROM poster_cache WHERE LOWER(normalized_title) LIKE ?"
        params = [f"{prefix}%"]
        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        sql += " ORDER BY priority DESC, id DESC"
        return self.execute_query(sql, params, fetch_all=True) or []
