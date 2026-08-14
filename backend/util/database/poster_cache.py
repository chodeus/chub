import json
from typing import Optional

from backend.util.helper import parse_search_id
from backend.util.normalization import normalize_titles

from .db_base import DatabaseBase, escape_like


# Additional-artwork image_type values (everything that isn't a poster and
# isn't an unprocessed banner). browse(image_type="artwork") matches this set
# so the asset-search page can show only logos/square art/backgrounds.
ARTWORK_IMAGE_TYPES = ("logo", "squareart", "background")


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
    def _image_type_clause(image_type: Optional[str]) -> tuple:
        """Return an ``(sql_fragment, params)`` pair for filtering by image_type.

        ``image_type=None`` means "all types" (no filter). Every read/match
        method below defaults the parameter to ``"poster"`` so that adding the
        non-poster asset types (logo/squareart/background/banner) to this shared
        table does not leak them into poster matching or the poster UI. Pass an
        explicit type (or None) from the asset pipeline.
        """
        if image_type is None:
            return "", []
        if image_type == "artwork":
            # The whole additional-artwork set (logo/squareart/background).
            placeholders = ",".join("?" * len(ARTWORK_IMAGE_TYPES))
            return f" AND image_type IN ({placeholders})", list(ARTWORK_IMAGE_TYPES)
        return " AND image_type=?", [image_type]

    @staticmethod
    def _title_search_clause(query: str) -> tuple:
        """Return an ``(sql, params)`` filter matching normalized_title, raw
        title, and external ids.

        A ``*`` in the query is a wildcard (SQL ``LIKE %``): ``*1952`` matches
        titles ENDING in 1952, ``1952*`` those STARTING with it, ``*1952*``
        anywhere. Literal ``%``/``_``/``\\`` in the query are escaped so they
        match literally. With no ``*`` the query is a plain substring match
        (legacy behaviour), so existing searches are unchanged.

        Also matches an id pasted from a filename tag ({tmdb-…}/{tvdb-…}/
        {imdb-tt…}) or a bare IMDb id, so users can search by id (mirrors
        poster_cache.search / media_cache.search).
        """

        if "*" in query:
            parts = query.split("*")
            norm_pat = "%".join(escape_like(normalize_titles(p)) for p in parts)
            raw_pat = "%".join(escape_like(p) for p in parts)
            sub = [
                "normalized_title LIKE ? ESCAPE '\\'",
                "title LIKE ? ESCAPE '\\'",
            ]
            sub_params: list = [norm_pat, raw_pat]
        else:
            sub = [
                "normalized_title LIKE ? ESCAPE '\\'",
                "title LIKE ? ESCAPE '\\'",
            ]
            sub_params = [
                f"%{escape_like(normalize_titles(query))}%",
                f"%{escape_like(query)}%",
            ]

        tmdb, tvdb, imdb = parse_search_id(query)
        if tmdb is not None:
            sub.append("tmdb_id = ?")
            sub_params.append(tmdb)
        if tvdb is not None:
            sub.append("tvdb_id = ?")
            sub_params.append(tvdb)
        if imdb:
            sub.append("LOWER(imdb_id) = ?")
            sub_params.append(imdb.lower())

        return "(" + " OR ".join(sub) + ")", sub_params

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

    _UPSERT_SQL = """
            INSERT INTO poster_cache
                (asset_type, title, normalized_title, year,
                 tmdb_id, tvdb_id, imdb_id,
                 musicbrainz_id, parent_musicbrainz_id, parent_title,
                 parent_normalized_title,
                 season_number, folder, file, style,
                 created_at, priority, image_type, search_only)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title, year, tmdb_id, tvdb_id, imdb_id, season_number, file)
            DO UPDATE SET
                asset_type=excluded.asset_type,
                normalized_title=excluded.normalized_title,
                musicbrainz_id=excluded.musicbrainz_id,
                parent_musicbrainz_id=excluded.parent_musicbrainz_id,
                parent_title=excluded.parent_title,
                parent_normalized_title=excluded.parent_normalized_title,
                folder=excluded.folder,
                style=excluded.style,
                priority=excluded.priority,
                image_type=excluded.image_type,
                search_only=excluded.search_only
            """

    @staticmethod
    def _prepare_upsert(record: dict) -> tuple:
        """Normalize a record and return the param tuple for ``_UPSERT_SQL``.

        Mutates ``record`` in place to JSON-serialize its list/dict fields
        (preserving prior behavior). Shared by ``upsert`` and ``bulk_upsert``
        so single-row and batched writes stay byte-identical.
        """
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

        # image_type distinguishes posters from the additional asset types
        # (logo/squareart/background/banner) that now share this table. Defaults
        # to "poster" so legacy callers and rows that predate the column behave
        # exactly as before. See asset_renamerr / AssetRenamerrConfig.
        image_type = record.get("image_type") or "poster"

        # search_only: indexed for Assets Search but excluded from matching.
        # Defaults to 0 (matchable) so direct DB writes and source_dir assets
        # behave exactly as before. See schema.py / merge_gdrive_search_index.
        search_only = int(record.get("search_only") or 0)

        return (
            record.get("asset_type"),
            record["title"],
            record["normalized_title"],
            record["year"],
            record["tmdb_id"],
            record["tvdb_id"],
            record["imdb_id"],
            record.get("musicbrainz_id"),
            record.get("parent_musicbrainz_id"),
            record.get("parent_title"),
            record.get("parent_normalized_title"),
            record["season_number"],
            record["folder"],
            record["file"],
            record.get("style"),
            created_at,
            priority,
            image_type,
            search_only,
        )

    def upsert(self, record: dict) -> None:
        """Insert or update a single record in poster_cache table."""
        self.execute_query(self._UPSERT_SQL, self._prepare_upsert(record))

    def bulk_upsert(self, records: list, chunk_size: int = 500) -> int:
        """Upsert many records, batching each chunk into one transaction.

        Collapses the per-row connect+commit(+fsync) cycle that dominates
        large cache refreshes (e.g. a 34k-row gdrive folder) into one commit
        per ``chunk_size`` rows. Chunking (rather than a single giant txn)
        keeps WAL growth and write-lock hold time bounded and lets callers
        interleave progress heartbeats between chunks. Returns the number of
        records written.
        """
        written = 0
        chunk: list = []
        for record in records:
            chunk.append((self._UPSERT_SQL, self._prepare_upsert(record)))
            if len(chunk) >= chunk_size:
                self.execute_transaction(chunk)
                written += len(chunk)
                chunk = []
        if chunk:
            self.execute_transaction(chunk)
            written += len(chunk)
        return written

    def has_rows_under_prefix(self, path_prefix: str) -> bool:
        """True if any cache row's ``file`` lives under ``path_prefix``.

        Cheap existence check (LIMIT 1) used to guard skip-on-zero-change:
        a folder that synced 0 changes is only safe to skip-refresh if its
        slice is already present (otherwise a freshly-cleared/empty cache
        would be left stale).
        """
        prefix = path_prefix.rstrip("/") + "/"
        row = self.execute_query(
            "SELECT 1 FROM poster_cache WHERE file LIKE ? ESCAPE '\\' LIMIT 1",
            (escape_like(prefix) + "%",),
            fetch_one=True,
        )
        return row is not None

    def record_dimensions(self, poster_id: int, width: int, height: int) -> None:
        """Persist width/height for a poster row (populated lazily by the API)."""
        self.execute_query(
            "UPDATE poster_cache SET width=?, height=? WHERE id=?",
            (int(width), int(height), int(poster_id)),
        )

    def find_missing_dimensions(self, limit: int = 200) -> list:
        """Return up to `limit` rows whose width/height are still unrecorded."""
        # id-ordered so an incremental backfill walks the table in a stable
        # order instead of re-drawing an arbitrary batch each call.
        return (
            self.execute_query(
                "SELECT id, file FROM poster_cache "
                "WHERE width IS NULL OR height IS NULL ORDER BY id ASC LIMIT ?",
                (int(limit),),
                fetch_all=True,
            )
            or []
        )

    def find_low_resolution(
        self,
        min_width: int = 1000,
        limit: int = 200,
        image_type: Optional[str] = "poster",
    ) -> list:
        """
        Return posters whose stored width falls below `min_width`. Rows
        with no recorded width are excluded — use record_dimensions first.
        """
        it_sql, it_params = self._image_type_clause(image_type)
        rows = (
            self.execute_query(
                "SELECT * FROM poster_cache WHERE width IS NOT NULL AND width < ?"
                + it_sql
                + " ORDER BY width ASC LIMIT ?",
                (int(min_width), *it_params, int(limit)),
                fetch_all=True,
            )
            or []
        )
        return [dict(r) for r in rows]

    def added_since(
        self, iso_cutoff: str, limit: int = 500, image_type: Optional[str] = "poster"
    ) -> list:
        """Return poster_cache rows added at or after the ISO-8601 cutoff."""
        it_sql, it_params = self._image_type_clause(image_type)
        # The cutoff is caller-supplied, so its separator/offset needn't match the
        # stored form — compare instants. created_at is deliberately unindexed.
        rows = (
            self.execute_query(
                "SELECT * FROM poster_cache "
                "WHERE datetime(created_at) >= datetime(?)" + it_sql + " "
                "ORDER BY created_at DESC LIMIT ?",
                (iso_cutoff, *it_params, int(limit)),
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
        image_type: Optional[str] = "poster",
        conn=None,
    ) -> Optional[dict]:
        """Get poster cache record by ID field.

        Ordering enforces the bottom-wins source_dir contract — see
        CONTRACT block at top of file. ``image_type`` defaults to "poster";
        pass a specific asset type (or None for all) from the asset pipeline.
        """
        sql = f"SELECT * FROM poster_cache WHERE {id_field}=?"
        params = [id_val]

        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        it_sql, it_params = self._image_type_clause(image_type)
        sql += it_sql
        params.extend(it_params)

        # Search-only rows (gdrive-only assets) are never match candidates.
        sql += " AND search_only=0"

        if season_number is not None:
            sql += " AND season_number=?"
            params.append(season_number)
        else:
            sql += " AND season_number IS NULL"

        sql += " ORDER BY priority DESC, id DESC LIMIT 1"
        return self.execute_query(sql, params, fetch_one=True, conn=conn)

    def get_by_normalized_title(
        self,
        normalized_title: str,
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        asset_type: Optional[str] = None,
        image_type: Optional[str] = "poster",
    ) -> Optional[dict]:
        """Get poster cache record by normalized title.

        Ordering enforces the bottom-wins source_dir contract — see
        CONTRACT block at top of file. ``image_type`` defaults to "poster".
        """
        sql = "SELECT * FROM poster_cache WHERE normalized_title=?"
        params = [normalized_title]

        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        it_sql, it_params = self._image_type_clause(image_type)
        sql += it_sql
        params.extend(it_params)

        # Search-only rows (gdrive-only assets) are never match candidates.
        sql += " AND search_only=0"

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

    def clear(self) -> int:
        """Delete all rows from poster_cache; returns rows deleted."""
        return int(self.execute_query("DELETE FROM poster_cache") or 0)

    def analyze(self) -> None:
        """Refresh planner stats; without them the match queries mis-pick indexes."""
        self.execute_query("ANALYZE poster_cache")

    def delete_by_path_prefix(self, path_prefix: str) -> int:
        """Delete all rows whose `file` path lives under `path_prefix`.

        Used to refresh a single source-dir's slice of the cache (e.g. after
        a per-folder gdrive sync) without touching unrelated rows. Matches
        on the absolute path so two contributor folders that happen to share
        a leaf name can't accidentally clobber each other.
        """
        prefix = path_prefix.rstrip("/") + "/"
        # Escape LIKE metacharacters so a folder named e.g. `My_Movies` can't
        # match siblings via the `_`/`%` wildcards.
        like = escape_like(prefix)
        return self.execute_query(
            "DELETE FROM poster_cache WHERE file LIKE ? ESCAPE '\\'", (like + "%",)
        )

    def delete_asset_rows_by_path_prefix(self, path_prefix: str) -> int:
        """Delete non-poster rows (image_type != 'poster') under `path_prefix`.

        Used by asset_renamerr's standalone scan to refresh its asset rows for a
        source_dir WITHOUT touching the poster rows poster_renamerr owns in the
        shared poster_cache.
        """
        prefix = path_prefix.rstrip("/") + "/"
        like = escape_like(prefix)
        return self.execute_query(
            "DELETE FROM poster_cache WHERE file LIKE ? ESCAPE '\\' "
            "AND image_type != 'poster'",
            (like + "%",),
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
        self,
        query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        image_type: Optional[str] = "poster",
    ) -> dict:
        """Search poster_cache by normalized title with pagination."""
        conditions = []
        params: list = []

        if image_type is not None:
            conditions.append("image_type=?")
            params.append(image_type)

        if query:
            # Match the same normalization that built the `normalized_title`
            # column so hyphenated / special-char searches ("x-men") still
            # find rows where the stored value collapsed to "xmen". Fall back
            # to a raw `title LIKE` so exact stored substrings still hit too.
            sub = [
                "normalized_title LIKE ? ESCAPE '\\'",
                "title LIKE ? ESCAPE '\\'",
            ]
            sub_params: list = [
                f"%{escape_like(normalize_titles(query))}%",
                f"%{escape_like(query)}%",
            ]
            # Also match an id pasted from a filename tag ({tmdb-…}/{tvdb-…}/
            # {imdb-tt…}) or a bare IMDb id, so users can search by id.
            tmdb, tvdb, imdb = parse_search_id(query)
            if tmdb is not None:
                sub.append("tmdb_id = ?")
                sub_params.append(tmdb)
            if tvdb is not None:
                sub.append("tvdb_id = ?")
                sub_params.append(tvdb)
            if imdb:
                sub.append("LOWER(imdb_id) = ?")
                sub_params.append(imdb.lower())
            conditions.append("(" + " OR ".join(sub) + ")")
            params.extend(sub_params)

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

    def get_all_grouped(self, image_type: Optional[str] = "poster") -> dict:
        """Return all poster_cache records grouped by type."""
        all_records = self.get_all()
        grouped = {"movies": [], "shows": [], "seasons": [], "collections": []}
        for record in all_records:
            if (
                image_type is not None
                and (record.get("image_type") or "poster") != image_type
            ):
                continue
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

    def get_distinct_owners(self, image_type: Optional[str] = "poster") -> list:
        """Return distinct owner names derived from the folder path."""
        it_sql, it_params = self._image_type_clause(image_type)
        rows = (
            self.execute_query(
                "SELECT DISTINCT folder FROM poster_cache "
                "WHERE folder IS NOT NULL AND folder != ''" + it_sql,
                tuple(it_params),
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

    def get_distinct_styles(self, image_type: Optional[str] = "poster") -> list:
        """Return distinct non-empty style values stored on poster_cache rows."""
        it_sql, it_params = self._image_type_clause(image_type)
        rows = (
            self.execute_query(
                "SELECT DISTINCT style FROM poster_cache "
                "WHERE style IS NOT NULL AND style != ''" + it_sql,
                tuple(it_params),
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
        image_type: Optional[str] = "poster",
    ) -> dict:
        """Browse poster_cache with optional owner, type, style, and search filters."""
        conditions = []
        params: list = []

        if image_type == "artwork":
            # The whole additional-artwork set (logo/squareart/background),
            # excluding posters and unprocessed banners.
            placeholders = ",".join("?" * len(ARTWORK_IMAGE_TYPES))
            conditions.append(f"image_type IN ({placeholders})")
            params.extend(ARTWORK_IMAGE_TYPES)
        elif image_type is not None:
            conditions.append("image_type=?")
            params.append(image_type)

        if query:
            # Match the same normalization that built the `normalized_title`
            # column so hyphenated / special-char searches ("x-men") still
            # find rows where the stored value collapsed to "xmen". Fall back
            # to a raw `title LIKE` so exact stored substrings still hit too.
            # A '*' in the query acts as a wildcard (see _title_search_clause).
            sql, qp = self._title_search_clause(query)
            conditions.append(sql)
            params.extend(qp)

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
        self,
        title: str,
        length: int = 3,
        asset_type: Optional[str] = None,
        image_type: Optional[str] = "poster",
        conn=None,
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

        # normalized_title is already lowercased by normalize_titles (the same
        # function that built `prefix` above), so LOWER() here is redundant and
        # makes the column non-sargable — it forces a full table scan instead
        # of a range scan on poster_cache_normalized_title_idx. Comparing the
        # raw column lets SQLite use the index for the `prefix%` range.
        sql = "SELECT * FROM poster_cache WHERE normalized_title LIKE ?"
        params = [f"{prefix}%"]
        if asset_type:
            sql += " AND asset_type=?"
            params.append(asset_type)

        it_sql, it_params = self._image_type_clause(image_type)
        sql += it_sql
        params.extend(it_params)

        # Search-only rows (gdrive-only assets) are never match candidates.
        sql += " AND search_only=0"

        sql += " ORDER BY priority DESC, id DESC"
        return self.execute_query(sql, params, fetch_all=True, conn=conn) or []

    # --- poster_collections: user-curated sets of poster_cache rows ---

    def create_collection(
        self, name: str, description: Optional[str], created_at: str
    ) -> int:
        """Insert a poster collection and return its new id."""
        return self.execute_query(
            "INSERT INTO poster_collections (name, description, created_at) "
            "VALUES (?, ?, ?)",
            (name, description, created_at),
            last_row_id=True,
        )

    def get_collection_id_by_name(self, name: str) -> Optional[int]:
        """Id of the most recently created collection with this name, or None."""
        row = self.execute_query(
            "SELECT id FROM poster_collections WHERE name=? ORDER BY id DESC LIMIT 1",
            (name,),
            fetch_one=True,
        )
        return row["id"] if row else None

    def add_collection_item(self, collection_id: int, poster_id: int) -> None:
        """Add a poster to a collection; an already-present pair is ignored."""
        self.execute_query(
            "INSERT OR IGNORE INTO poster_collection_items "
            "(collection_id, poster_id) VALUES (?, ?)",
            (collection_id, poster_id),
        )

    def get_collections(self) -> list:
        """Return every poster collection, name-ascending."""
        # `name` isn't unique — id breaks the tie so the list order is stable.
        return (
            self.execute_query(
                "SELECT * FROM poster_collections ORDER BY name ASC, id ASC",
                fetch_all=True,
            )
            or []
        )

    def get_collection(self, collection_id: int) -> Optional[dict]:
        """Return one poster collection by id, or None."""
        return self.execute_query(
            "SELECT * FROM poster_collections WHERE id=?",
            (collection_id,),
            fetch_one=True,
        )

    def get_collection_posters(self, collection_id: int) -> list:
        """Return the display fields of every poster in one collection."""
        return (
            self.execute_query(
                "SELECT p.id, p.asset_type, p.title, p.year, p.season_number, "
                "p.folder, p.file, p.style "
                "FROM poster_collection_items pci "
                "JOIN poster_cache p ON p.id = pci.poster_id "
                "WHERE pci.collection_id = ? "
                "ORDER BY p.title ASC, p.id ASC",
                (collection_id,),
                fetch_all=True,
            )
            or []
        )

    def remove_collection_item(self, collection_id: int, poster_id: int) -> int:
        """Drop one poster from one collection; returns rows deleted."""
        # Both columns: (collection_id, poster_id) is the pair's unique key, so
        # the same poster stays in every other collection.
        return (
            self.execute_query(
                "DELETE FROM poster_collection_items "
                "WHERE collection_id=? AND poster_id=?",
                (collection_id, poster_id),
            )
            or 0
        )

    def delete_collection(self, collection_id: int) -> None:
        """Delete a collection and its membership rows in one transaction."""
        # One transaction: a half-applied delete would leave orphaned items
        # pointing at a collection that no longer exists.
        self.execute_transaction(
            [
                (
                    "DELETE FROM poster_collection_items WHERE collection_id=?",
                    (collection_id,),
                ),
                ("DELETE FROM poster_collections WHERE id=?", (collection_id,)),
            ]
        )
