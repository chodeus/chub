import json
from typing import Any, List, Optional

from backend.util.normalization import normalize_titles

from .db_base import DatabaseBase


class MediaCache(DatabaseBase):
    """
    Interface for the media_cache table.
    Provides CRUD and sync operations for tracked media assets.
    """

    @staticmethod
    def _identity_key(item: dict, asset_type: str, instance_name: str) -> str:
        """Build a stable, non-NULL identity string for media items.
        Rules:
          - Prefer imdb; else tmdb (movies); else tvdb (shows); else title+year fallback.
          - Omit the season segment entirely when there is no season; include `|s:0` for specials, `|s:N` for seasons.
        """

        def norm_int(v):
            if v in (None, "", "None"):
                return None
            try:
                return int(v)
            except Exception:
                return None

        def norm_str(v):
            if v in (None, "", "None"):
                return None
            return str(v).strip()

        tmdb = norm_int(item.get("tmdb_id"))
        tvdb = norm_int(item.get("tvdb_id"))
        imdb = norm_str(item.get("imdb_id"))
        title_key = norm_str(item.get("normalized_title") or item.get("title")) or ""
        year_key = norm_int(item.get("year")) or -1

        musicbrainz = norm_str(item.get("musicbrainz_id"))

        # choose stable cross-source id
        if asset_type == "artist" and musicbrainz:
            id_tag = f"mb:{musicbrainz}"
        elif imdb:
            id_tag = f"imdb:{imdb.lower()}"
        elif asset_type == "movie" and tmdb:
            id_tag = f"tmdb:{tmdb}"
        elif asset_type != "movie" and tvdb:
            id_tag = f"tvdb:{tvdb}"
        else:
            id_tag = f"title:{title_key}|y:{year_key}"

        # Season segment only when present (0..N). Omit for movies and series-root.
        season_raw = item.get("season_number")
        season_val = norm_int(season_raw)
        has_season = (asset_type != "movie") and (season_val is not None)
        season_seg = f"|s:{season_val}" if has_season else ""

        return f"{instance_name}|{asset_type}|{id_tag}{season_seg}"

    def upsert(
        self,
        item: dict,
        asset_type: str,
        instance_type: str,
        instance_name: str,
    ) -> None:
        """
        Insert or update a single media record for a given instance/asset_type.
        """
        required_keys = [
            "title",
            "normalized_title",
            "alternate_titles",
            "normalized_alternate_titles",
            "year",
            "tmdb_id",
            "tvdb_id",
            "imdb_id",
            "musicbrainz_id",
            "folder",
            "root_folder",
            "media_file",
            "location",
            "tags",
            "season_number",
            "poster_url",
            "arr_id",
            # Advanced search filtering fields
            "status",
            "rating",
            "studio",
            "edition",
            "runtime",
            "language",
            "monitored",
            "has_content",
            "genre",
        ]
        record = {k: item.get(k) for k in required_keys}
        record["asset_type"] = asset_type
        record["instance_name"] = instance_name
        record["source"] = instance_type
        if asset_type == "movie":
            record["season_number"] = None

        for field in [
            "year",
            "tmdb_id",
            "tvdb_id",
            "imdb_id",
            "musicbrainz_id",
            "season_number",
            "poster_url",
            "arr_id",
            "runtime",
        ]:
            if record[field] == "" or (
                isinstance(record[field], str) and record[field].strip() == ""
            ):
                record[field] = None

        tags_value = item.get("tags")
        if tags_value is None:
            record["tags"] = json.dumps([])
        elif isinstance(tags_value, str):
            record["tags"] = tags_value
        else:
            record["tags"] = json.dumps(tags_value)

        for key in ("alternate_titles", "normalized_alternate_titles"):
            value = item.get(key)
            if value is None:
                record[key] = json.dumps([])
            elif isinstance(value, str):
                record[key] = value
            else:
                record[key] = json.dumps(value)

        identity_key = self._identity_key(record, asset_type, instance_name)

        self.execute_query(
            """
            INSERT INTO media_cache
                (identity_key, asset_type, title, normalized_title,
                alternate_titles, normalized_alternate_titles,
                year, tmdb_id, tvdb_id, imdb_id, musicbrainz_id, folder, root_folder, media_file, tags,
                season_number, matched, instance_name, source, poster_url, arr_id,
                status, rating, studio, edition, runtime, language, monitored, has_content, genre)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(identity_key)
            DO UPDATE SET
                title=excluded.title,
                year=excluded.year,
                -- Refresh secondary IDs too: when the row is keyed on one id
                -- (e.g. imdb) and a *different* id changes on the *arr's side
                -- (TVDb in particular re-issues ids), the stale value would
                -- otherwise persist and break id-based matching / request
                -- links. The key id itself is unchanged here by definition.
                tmdb_id=excluded.tmdb_id,
                tvdb_id=excluded.tvdb_id,
                imdb_id=excluded.imdb_id,
                normalized_title=excluded.normalized_title,
                alternate_titles=excluded.alternate_titles,
                normalized_alternate_titles=excluded.normalized_alternate_titles,
                folder=excluded.folder,
                root_folder=excluded.root_folder,
                media_file=excluded.media_file,
                tags=excluded.tags,
                source=excluded.source,
                poster_url=excluded.poster_url,
                arr_id=excluded.arr_id,
                musicbrainz_id=excluded.musicbrainz_id,
                status=excluded.status,
                rating=excluded.rating,
                studio=excluded.studio,
                edition=excluded.edition,
                runtime=excluded.runtime,
                language=excluded.language,
                monitored=excluded.monitored,
                has_content=excluded.has_content,
                genre=excluded.genre
                -- Preserve: matched, original_file, renamed_file, file_hash, plex_mapping_id
                -- These fields should only be updated by specific operations, not ARR sync
            """,
            (
                identity_key,
                record["asset_type"],
                record["title"],
                record["normalized_title"],
                record["alternate_titles"],
                record["normalized_alternate_titles"],
                record["year"],
                record["tmdb_id"],
                record["tvdb_id"],
                record["imdb_id"],
                record.get("musicbrainz_id") or None,
                record["folder"],
                record.get("root_folder") or None,
                record.get("media_file") or None,
                record["tags"],
                record["season_number"],
                0,
                instance_name,
                instance_type,
                record.get("poster_url") or None,
                record.get("arr_id") or None,
                record.get("status") or None,
                record.get("rating") or None,
                record.get("studio") or None,
                record.get("edition") or None,
                record.get("runtime") or None,
                record.get("language") or None,
                record.get("monitored", True),  # Default to True if not specified
                int(bool(record.get("has_content", True))),
                record.get("genre") or None,
            ),
        )

    @staticmethod
    def _canonical_key(item: dict, asset_type: str, instance_name: str) -> tuple:
        """Returns the unique key for media_cache."""
        if asset_type == "movie":
            item["season_number"] = None

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
            asset_type,
            norm_str(item.get("title", "")),
            norm_int(item.get("year")),
            norm_int(item.get("tmdb_id")),
            norm_int(item.get("tvdb_id")),
            norm_str(item.get("imdb_id")),
            norm_int(item.get("season_number")),
            str(instance_name),
        )

    def get_by_instance(self, instance_name: str) -> list:
        """Return all media_cache records for the given instance."""
        return (
            self.execute_query(
                "SELECT * FROM media_cache WHERE instance_name=?",
                (instance_name,),
                fetch_all=True,
            )
            or []
        )

    def get_by_id(self, id: int) -> Optional[dict]:
        """Return a single media_cache row by its unique integer ID."""
        return self.execute_query(
            "SELECT * FROM media_cache WHERE id=?", (id,), fetch_one=True
        )

    def get_all(self) -> list:
        """Return all records from media_cache as a list of dicts."""
        return self.execute_query("SELECT * FROM media_cache", fetch_all=True) or []

    def get_unmatched(self) -> list:
        """Return all media_cache records where matched=0."""
        return (
            self.execute_query(
                "SELECT * FROM media_cache WHERE matched=0", fetch_all=True
            )
            or []
        )

    def reset_match_state(self) -> int:
        """Reset poster-match coverage to all-missing for rows the user hasn't
        curated.

        Clears the ``matched`` flag and all match metadata (status/confidence/
        reason + the matched poster file/timestamp) so the next poster_renamerr
        run re-matches from scratch. Preserves user-curated rows — ignored
        (dismissed) and user_confirmed (locked) — and the plex_mapping_id Plex
        identity (not poster-match state). Returns the number of previously
        matched rows that were reset.
        """
        predicate = (
            "(ignored IS NULL OR ignored = 0) "
            "AND (user_confirmed IS NULL OR user_confirmed = 0)"
        )
        # Scope COUNT and UPDATE identically so the returned count matches the
        # rows actually cleared. Include needs_review rows (match_status set but
        # matched = 0) — they carry match metadata that the reset clears too —
        # while excluding never-evaluated rows (no flag, no status).
        scope = f"(matched = 1 OR match_status IS NOT NULL) AND {predicate}"
        row = self.execute_query(
            f"SELECT COUNT(*) AS n FROM media_cache WHERE {scope}",
            fetch_one=True,
        )
        reset_count = int(row["n"]) if row else 0
        self.execute_query(
            "UPDATE media_cache SET matched = 0, match_status = NULL, "
            "match_confidence = NULL, match_reason = NULL, "
            "matched_poster_file = NULL, matched_at = NULL "
            f"WHERE {scope}"
        )
        return reset_count

    def get_needs_review(self) -> list:
        """Return rows flagged for human review (weak/ambiguous/unverified
        candidate), excluding ones the user has ignored."""
        return (
            self.execute_query(
                "SELECT * FROM media_cache "
                "WHERE match_status='needs_review' "
                "AND (ignored IS NULL OR ignored=0)",
                fetch_all=True,
            )
            or []
        )

    def get_ignored(self) -> list:
        """Return rows the user has dismissed (ignored=1)."""
        return (
            self.execute_query(
                "SELECT * FROM media_cache WHERE ignored=1", fetch_all=True
            )
            or []
        )

    def set_ignored(self, id: int, ignored: bool) -> None:
        """Toggle the user-dismissal flag for one media row."""
        self.execute_query(
            "UPDATE media_cache SET ignored=? WHERE id=?",
            (int(bool(ignored)), id),
        )

    def get_user_confirmed(self) -> list:
        """Return rows the user manually locked (user_confirmed=1) — surfaced in
        the Locked tab so they can be re-opened for review."""
        return (
            self.execute_query(
                "SELECT * FROM media_cache WHERE user_confirmed=1", fetch_all=True
            )
            or []
        )

    def set_user_confirmed(self, id: int, confirmed: bool) -> None:
        """Toggle the manual-pick lock for one media row. While set, match_item
        leaves the row's match untouched on re-scans."""
        self.execute_query(
            "UPDATE media_cache SET user_confirmed=? WHERE id=?",
            (int(bool(confirmed)), id),
        )

    def set_match_provenance(
        self, id: int, matched_at: Optional[str], matched_poster_file: Optional[str]
    ) -> None:
        """Record (or clear, with None) when/what poster a media row matched.

        Done via a dedicated setter rather than update() because both fields
        must be settable to NULL on a no-match, which update()'s
        "None = leave untouched" convention can't express.
        """
        self.execute_query(
            "UPDATE media_cache SET matched_at=?, matched_poster_file=? WHERE id=?",
            (matched_at, matched_poster_file, id),
        )

    def get_recently_matched(self, limit: int = 50) -> list:
        """Return the poster_cache rows for the most-recently-matched media and
        collections, newest first.

        Links by file path (not poster_cache.id) so it survives the cache's
        clear-and-reinsert on every scan. UNIONs media + collections so the
        reel covers movies, shows, seasons, and collections.
        """
        return (
            self.execute_query(
                """
                SELECT pc.*, m.matched_at AS matched_at
                FROM poster_cache pc
                JOIN (
                    SELECT matched_poster_file, matched_at
                    FROM media_cache
                    WHERE matched_poster_file IS NOT NULL AND matched_at IS NOT NULL
                    UNION ALL
                    SELECT matched_poster_file, matched_at
                    FROM collections_cache
                    WHERE matched_poster_file IS NOT NULL AND matched_at IS NOT NULL
                ) m ON pc.file = m.matched_poster_file
                ORDER BY m.matched_at DESC
                LIMIT ?
                """,
                (limit,),
                fetch_all=True,
            )
            or []
        )

    def clear(self) -> None:
        """Delete all rows from media_cache."""
        self.execute_query("DELETE FROM media_cache")

    def clear_by_instance_and_type(self, instance_name, asset_type) -> None:
        """Delete all rows from media_cache for a given instance and asset_type."""
        self.execute_query(
            "DELETE FROM media_cache WHERE instance_name=? AND asset_type=?",
            (instance_name, asset_type),
        )

    def delete(
        self,
        item: dict,
        instance_name: str,
        asset_type: str,
        logger: Optional[Any] = None,
    ) -> None:
        """Delete a single record by its identity key.

        Called from sync_for_instance to drop rows that the *arr no longer
        reports (e.g. a Sonarr series whose unreleased season vanished from
        the API response, an unmonitored show pruned from the library, a
        deleted movie). Used to be gated on `renamed_file` while the
        pending_deletions ledger was in play — that ledger was ripped out in
        the cleanarr rewrite but the guard accidentally stayed, which left
        stale rows lingering forever. In particular, rows that pre-dated
        the has_content column kept the backfill-migration's NULL value and
        slipped past the unmatched_assets has_content gate even though the
        *arr no longer tracks them. Always delete now.
        """
        identity_key = self._identity_key(item, asset_type, instance_name)
        self.execute_query(
            "DELETE FROM media_cache WHERE identity_key = ?",
            (identity_key,),
        )
        if logger:
            season = item.get("season_number")
            season_str = f" Season: {season}," if season is not None else ""
            logger.debug(
                f"[DELETE] Title: {item.get('title')} ({item.get('year')}) ({asset_type}),{season_str} from {instance_name}"
            )

    def get_by_title_year_instance(
        self, title: str, year: int = None, instance_name: str = None
    ):
        """
        Get media records by title, year, and instance name.
        Returns list of records including seasons for shows.
        """
        query = """
            SELECT * FROM media_cache 
            WHERE title = ? AND instance_name = ?
        """
        params = [title, instance_name]

        if year is not None:
            query += " AND year = ?"
            params.append(year)

        query += " ORDER BY season_number ASC NULLS FIRST"

        return self.execute_query(query, tuple(params), fetch_all=True)

    def delete_by_id(self, id: int) -> None:
        """Delete a single record by its unique integer ID."""
        self.execute_query("DELETE FROM media_cache WHERE id=?", (id,))

    def get_by_keys(
        self,
        asset_type: str,
        title: str,
        year: str,
        tmdb_id: int,
        tvdb_id: int,
        imdb_id: str,
        season_number: int,
        instance_name: str,
    ) -> List[dict]:
        """Get records by specific keys - handles shows with multiple seasons."""
        # If asset_type is 'show' and season_number is None, get all seasons and the show record
        if asset_type == "show" and season_number is None:
            query = """
            SELECT * FROM media_cache
            WHERE asset_type=? AND title=? AND year IS ?
            AND tmdb_id IS ? AND tvdb_id IS ? AND imdb_id IS ?
            AND instance_name=?
            """
            params = (
                asset_type,
                title,
                year if year not in ("", None) else None,
                tmdb_id if tmdb_id not in ("", None) else None,
                tvdb_id if tvdb_id not in ("", None) else None,
                imdb_id if imdb_id not in ("", None) else None,
                instance_name,
            )
            rows = self.execute_query(query, params, fetch_all=True)
            return rows or []
        else:
            # regular case: one record
            query = """
            SELECT * FROM media_cache
            WHERE asset_type=? AND title=? AND year IS ?
            AND tmdb_id IS ? AND tvdb_id IS ? AND imdb_id IS ?
            AND season_number IS ? AND instance_name=?
            """
            params = (
                asset_type,
                title,
                year if year not in ("", None) else None,
                tmdb_id if tmdb_id not in ("", None) else None,
                tvdb_id if tvdb_id not in ("", None) else None,
                imdb_id if imdb_id not in ("", None) else None,
                season_number if season_number not in ("", None) else None,
                instance_name,
            )
            rows = self.execute_query(query, params, fetch_all=True)
            return rows or []

    def update(
        self,
        asset_type: str,
        title: str,
        year: Optional[Any],
        instance_name: str,
        matched_value: Optional[Any] = None,
        season_number: Optional[Any] = None,
        original_file: Optional[Any] = None,
        renamed_file: Optional[Any] = None,
        file_hash: Optional[Any] = None,
        file_mtime: Optional[Any] = None,
        uploaded_libraries: Optional[Any] = None,
        poster_url: Optional[Any] = None,
        arr_id: Optional[Any] = None,
        tmdb_id: Optional[Any] = None,
        # Advanced search fields
        status: Optional[Any] = None,
        rating: Optional[Any] = None,
        studio: Optional[Any] = None,
        edition: Optional[Any] = None,
        runtime: Optional[Any] = None,
        language: Optional[Any] = None,
        monitored: Optional[Any] = None,
        # Match transparency / lifecycle fields. Each is only written when
        # explicitly passed (None = leave untouched), so the rename phase can
        # clear `matched` without wiping match_status/reason.
        match_status: Optional[Any] = None,
        match_confidence: Optional[Any] = None,
        match_reason: Optional[Any] = None,
        ignored: Optional[Any] = None,
        conflict_ids: Optional[Any] = None,
        rename_history: Optional[Any] = None,
        id: Optional[Any] = None,
    ) -> None:
        """Update fields for a given media record."""
        set_clauses = []
        params = []

        if matched_value is not None:
            set_clauses.append("matched=?")
            params.append(int(bool(matched_value)))

        if original_file is not None:
            set_clauses.append("original_file=?")
            params.append(original_file)

        if renamed_file is not None:
            set_clauses.append("renamed_file=?")
            params.append(renamed_file)

        if file_hash is not None:
            set_clauses.append("file_hash=?")
            params.append(file_hash)

        if file_mtime is not None:
            set_clauses.append("file_mtime=?")
            params.append(float(file_mtime))

        if uploaded_libraries is not None:
            set_clauses.append("uploaded_libraries=?")
            params.append(uploaded_libraries)

        if poster_url is not None:
            set_clauses.append("poster_url=?")
            params.append(poster_url)

        if arr_id is not None:
            set_clauses.append("arr_id=?")
            params.append(arr_id)

        if tmdb_id is not None:
            set_clauses.append("tmdb_id=?")
            params.append(int(tmdb_id))

        # Advanced search fields
        if status is not None:
            set_clauses.append("status=?")
            params.append(status)

        if rating is not None:
            set_clauses.append("rating=?")
            params.append(rating)

        if studio is not None:
            set_clauses.append("studio=?")
            params.append(studio)

        if edition is not None:
            set_clauses.append("edition=?")
            params.append(edition)

        if runtime is not None:
            set_clauses.append("runtime=?")
            params.append(runtime)

        if language is not None:
            set_clauses.append("language=?")
            params.append(language)

        if monitored is not None:
            set_clauses.append("monitored=?")
            params.append(int(bool(monitored)))

        if match_status is not None:
            set_clauses.append("match_status=?")
            params.append(match_status)

        if match_confidence is not None:
            set_clauses.append("match_confidence=?")
            params.append(float(match_confidence))

        if match_reason is not None:
            set_clauses.append("match_reason=?")
            params.append(match_reason)

        if ignored is not None:
            set_clauses.append("ignored=?")
            params.append(int(bool(ignored)))

        if conflict_ids is not None:
            set_clauses.append("conflict_ids=?")
            params.append(conflict_ids)

        if rename_history is not None:
            set_clauses.append("rename_history=?")
            params.append(rename_history)

        if not set_clauses:
            return

        if id is not None:
            query = f"""
                UPDATE media_cache
                SET {", ".join(set_clauses)}
                WHERE id=?
            """
            params.append(id)
            self.execute_query(query, tuple(params))
            return

        query = f"""
            UPDATE media_cache
            SET {", ".join(set_clauses)}
            WHERE asset_type=? AND title=? AND instance_name=?
        """
        params.extend([asset_type, title, instance_name])

        if year is None:
            query += " AND year IS NULL"
        else:
            query += " AND year=?"
            params.append(year)

        if season_number is None:
            query += " AND season_number IS NULL"
        else:
            query += " AND season_number=?"
            params.append(season_number)

        self.execute_query(query, tuple(params))

    def search(
        self,
        query: Optional[str] = None,
        asset_type: Optional[str] = None,
        genres: Optional[List[str]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        rating_min: Optional[float] = None,
        rating_max: Optional[float] = None,
        instance_name: Optional[str] = None,
        matched: Optional[int] = None,
        sort: str = "title",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Search media_cache with filters and pagination.

        Args:
            query: Free-text search matched against title fields.
            asset_type: Filter by asset type (movie, show, all).
            genres: List of genre strings to match (OR logic).
            year_min: Minimum release year (inclusive).
            year_max: Maximum release year (inclusive).
            rating_min: Minimum rating value (inclusive, cast from TEXT).
            rating_max: Maximum rating value (inclusive, cast from TEXT).
            instance_name: Restrict results to a single instance.
            matched: Filter by matched flag (0 or 1).
            sort: Column to sort by (title, year, rating).
            order: Sort direction (asc or desc).
            limit: Maximum rows to return.
            offset: Number of rows to skip.

        Returns:
            Dict with ``items``, ``total``, ``limit``, and ``offset``.
        """
        conditions: List[str] = []
        params: List[Any] = []

        if query:
            # Normalize the query for the normalized_title column so
            # hyphenated / special-char searches ("X-Men:") hit the rows
            # whose normalized form has the punctuation stripped. Raw
            # title LIKE is the case-insensitive fallback for exact
            # stored substrings. Same fix as poster_cache.search.
            conditions.append("(normalized_title LIKE ? OR title LIKE ?)")
            params.extend([f"%{normalize_titles(query)}%", f"%{query}%"])

        if asset_type and asset_type != "all":
            conditions.append("asset_type = ?")
            params.append(asset_type)

        if genres:
            genre_conditions = ["genre LIKE ?" for _ in genres]
            conditions.append(f"({' OR '.join(genre_conditions)})")
            params.extend(f"%{g}%" for g in genres)

        if year_min is not None:
            conditions.append("CAST(year AS INTEGER) >= ?")
            params.append(year_min)
        if year_max is not None:
            conditions.append("CAST(year AS INTEGER) <= ?")
            params.append(year_max)

        if rating_min is not None:
            conditions.append(
                "rating IS NOT NULL AND rating != '' AND CAST(rating AS REAL) >= ?"
            )
            params.append(rating_min)
        if rating_max is not None:
            conditions.append(
                "rating IS NOT NULL AND rating != '' AND CAST(rating AS REAL) <= ?"
            )
            params.append(rating_max)

        if instance_name:
            conditions.append("instance_name = ?")
            params.append(instance_name)

        if matched is not None:
            conditions.append("matched = ?")
            params.append(matched)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_result = self.execute_query(
            f"SELECT COUNT(*) as total FROM media_cache {where}",
            tuple(params),
            fetch_one=True,
        )
        total = count_result["total"] if count_result else 0

        sort_col = {
            "title": "normalized_title",
            "year": "CAST(year AS INTEGER)",
            "rating": "rating",
            "runtime": "CAST(runtime AS INTEGER)",
        }.get(sort, "normalized_title")
        order_dir = "DESC" if order == "desc" else "ASC"

        data_params = list(params) + [limit, offset]
        items = (
            self.execute_query(
                f"SELECT * FROM media_cache {where} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?",
                tuple(data_params),
                fetch_all=True,
            )
            or []
        )

        return {"items": items, "total": total, "limit": limit, "offset": offset}

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

        rows = (
            self.execute_query(
                f"""
                SELECT asset_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) as matched,
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
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) as matched
            FROM media_cache {where}
            """,
            params,
            fetch_one=True,
        )

        return {
            "by_type": rows,
            "total": totals["total"] if totals else 0,
            "matched": totals["matched"] if totals else 0,
            "unmatched": (totals["total"] or 0) - (totals["matched"] or 0)
            if totals
            else 0,
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

        # By instance
        by_instance = (
            self.execute_query(
                f"""SELECT instance_name, COUNT(*) as total,
                       SUM(CASE WHEN matched=1 THEN 1 ELSE 0 END) as matched
                FROM media_cache {where}
                GROUP BY instance_name ORDER BY total DESC""",
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

        return {
            **base,
            "by_instance": by_instance,
            "by_status": by_status,
            "by_language": by_language,
            "by_rating": by_rating,
            "by_studio": by_studio,
            "by_decade": by_decade,
            "by_runtime": by_runtime,
            "by_genre": by_genre,
            "monitored": monitored,
        }

    def get_distinct_genres(self, asset_type: Optional[str] = None) -> List[str]:
        """Extract unique genres from all media_cache entries."""
        where = ""
        params: tuple = ()
        if asset_type and asset_type != "all":
            where = "AND asset_type = ?"
            params = (asset_type,)

        rows = (
            self.execute_query(
                f"SELECT DISTINCT genre FROM media_cache WHERE genre IS NOT NULL AND genre != '' {where}",
                params,
                fetch_all=True,
            )
            or []
        )

        genres: set = set()
        for row in rows:
            raw = row.get("genre", "")
            if not raw:
                continue
            # Handle JSON array format
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    genres.update(str(g).strip() for g in parsed if g)
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
            # Handle comma-separated or plain text
            for g in raw.split(","):
                g = g.strip()
                if g:
                    genres.add(g)

        return sorted(genres)

    def find_duplicates(self, asset_type: Optional[str] = None) -> list:
        """Find genuine duplicate media entries WITHIN a single instance.

        Identity-based detection: two or more media_cache rows from the
        same ARR instance that share the same external ID (musicbrainz
        for artists, otherwise tvdb_id / tmdb_id / imdb_id). Rows
        without any external ID are excluded — they can't be matched
        safely.

        Season rows are excluded so a multi-season show isn't reported
        as duplicates of itself. Cross-instance overlap (Radarr +
        Radarr4K) is intentional quality coverage and is NOT reported.
        """
        where = ""
        params: tuple = ()
        if asset_type and asset_type != "all":
            where = "AND asset_type = ?"
            params = (asset_type,)

        return (
            self.execute_query(
                f"""
                SELECT MIN(normalized_title) as normalized_title,
                       MIN(title) as title,
                       MIN(year) as year,
                       instance_name,
                       COUNT(*) as count,
                       GROUP_CONCAT(id) as ids,
                       GROUP_CONCAT(instance_name) as instances,
                       json_group_array(folder) as folders,
                       COALESCE(
                           'mb:' || musicbrainz_id,
                           'tvdb:' || tvdb_id,
                           'tmdb:' || tmdb_id,
                           'imdb:' || imdb_id
                       ) as identity
                FROM media_cache
                WHERE season_number IS NULL
                  AND (musicbrainz_id IS NOT NULL
                       OR tvdb_id IS NOT NULL
                       OR tmdb_id IS NOT NULL
                       OR imdb_id IS NOT NULL)
                  {where}
                GROUP BY instance_name, identity
                HAVING COUNT(*) > 1
                ORDER BY count DESC
                """,
                params,
                fetch_all=True,
            )
            or []
        )

    def find_folder_collisions(self, asset_type: Optional[str] = None) -> list:
        """Find rows whose folders look like the same item but have
        ambiguous external IDs.

        Two rows within the same instance share a normalized title but
        differ in external IDs (tvdb / tmdb / imdb / musicbrainz). We
        only surface a collision when at least one row is missing an
        external ID — that's when the user genuinely can't tell the
        rows apart from metadata alone.

        When every row has a distinct external ID of its own, the items
        are unambiguously different (e.g. ``Destination X (US)`` vs
        ``Destination X (UK)``, or REZZ the EDM producer vs REZZ the
        pop artist). Those are suppressed; the user has already
        organized them.
        """
        where = ""
        params: tuple = ()
        if asset_type and asset_type != "all":
            where = "AND asset_type = ?"
            params = (asset_type,)

        rows = (
            self.execute_query(
                f"""
                SELECT id, title, normalized_title, year, instance_name,
                       folder, tvdb_id, tmdb_id, imdb_id, musicbrainz_id,
                       asset_type
                FROM media_cache
                WHERE season_number IS NULL
                  AND normalized_title IS NOT NULL
                  AND normalized_title != ''
                  {where}
                """,
                params,
                fetch_all=True,
            )
            or []
        )

        # Group by (instance, normalized_title, year) and only keep
        # groups whose external IDs are not all the same — i.e. the
        # title looks duplicated but the items are different shows.
        groups: dict = {}
        for r in rows:
            key = (r.get("instance_name"), r.get("normalized_title"), r.get("year"))
            groups.setdefault(key, []).append(r)

        collisions = []
        for (instance, norm_title, year), members in groups.items():
            if len(members) < 2:
                continue

            # Best external ID per row, in priority order. None means
            # the row has no external ID at all.
            per_row_ids: list = []
            for m in members:
                mbid = m.get("musicbrainz_id")
                tvdb = m.get("tvdb_id")
                tmdb = m.get("tmdb_id")
                imdb = m.get("imdb_id")
                if mbid:
                    per_row_ids.append(f"mb:{mbid}")
                elif tvdb is not None:
                    per_row_ids.append(f"tvdb:{tvdb}")
                elif tmdb is not None:
                    per_row_ids.append(f"tmdb:{tmdb}")
                elif imdb is not None:
                    per_row_ids.append(f"imdb:{imdb}")
                else:
                    per_row_ids.append(None)

            # Every row has a real external ID and they're all distinct
            # → unambiguously different items the user has already
            # organized (Destination X US/UK, REZZ EDM/pop, etc.).
            if all(per_row_ids) and len(set(per_row_ids)) == len(per_row_ids):
                continue

            identities = set()
            for i, m in enumerate(members):
                identities.add(per_row_ids[i] or f"row:{m.get('id')}")

            # All members share the same external ID → it's a genuine
            # duplicate, handled by find_duplicates(). Skip here.
            if len(identities) < 2:
                continue

            collisions.append(
                {
                    "normalized_title": norm_title,
                    "title": members[0].get("title"),
                    "year": year,
                    "instance_name": instance,
                    "count": len(members),
                    "ids": ",".join(str(m.get("id", "")) for m in members),
                    "instances": ",".join(
                        m.get("instance_name", "") for m in members
                    ),
                    "folders": json.dumps(
                        [m.get("folder") or "" for m in members]
                    ),
                    "identities": ",".join(sorted(identities)),
                    "titles": json.dumps([m.get("title") or "" for m in members]),
                }
            )

        collisions.sort(key=lambda c: c["count"], reverse=True)
        return collisions

    def sync_for_instance(
        self,
        instance_name: str,
        instance_type: str,
        asset_type: str,
        fresh_media: list,
        logger: Optional[Any] = None,
    ) -> None:
        """
        Syncs the media_cache table for a specific instance and asset_type to match fresh_media.
        Adds/updates as needed, deletes stale records not present in fresh_media.
        """
        db_rows = (
            self.execute_query(
                "SELECT * FROM media_cache WHERE instance_name=? AND asset_type=?",
                (instance_name, asset_type),
                fetch_all=True,
            )
            or []
        )

        def row_identity(row):
            return row["identity_key"]

        db_map = {row_identity(row): row for row in db_rows}
        fresh_map = {
            self._identity_key(item, asset_type, instance_name): item
            for item in fresh_media
        }

        # Add/update items that are present in fresh_media
        for key, item in fresh_map.items():
            # Use standard upsert (now includes genre and cast as simple fields)
            self.upsert(item, asset_type, instance_type, instance_name)

            if key not in db_map and logger:
                season = item.get("season_number")
                season_str = f" Season: {season}," if season is not None else ""
                logger.debug(
                    f"[ADD] Title: {item.get('title')} ({item.get('year')}) ({asset_type}),{season_str} from {instance_name}"
                )

        # Remove items that are no longer present
        keys_to_remove = set(db_map.keys()) - set(fresh_map.keys())
        for key in keys_to_remove:
            row = db_map[key]
            self.delete(row, instance_name, asset_type, logger)

        if logger:
            logger.info(
                f"[SYNC] Media cache for {instance_name} ({asset_type}) synchronized. {len(fresh_media)} items present."
            )
