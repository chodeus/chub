import json
from typing import Any, Optional

from .db_base import DatabaseBase


class CollectionCache(DatabaseBase):
    """
    Interface for the collections_cache table.
    Provides CRUD and sync operations.
    """

    def upsert(self, record: dict, instance_name: str) -> None:
        """Insert or update a collection record for a given instance."""
        record["instance_name"] = instance_name
        record["asset_type"] = "collection"

        # Serialize list/dict fields to JSON
        for key in ("alternate_titles", "normalized_alternate_titles"):
            if isinstance(record.get(key), (list, dict)):
                record[key] = json.dumps(record[key])
            elif record.get(key) is None:
                record[key] = json.dumps([])

        self.execute_query(
            """
            INSERT INTO collections_cache
                (asset_type, title, normalized_title, alternate_titles, normalized_alternate_titles, year,
                tmdb_id, tvdb_id, imdb_id, folder, library_name, instance_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title, library_name, instance_name)
            DO UPDATE SET
                year=excluded.year,
                normalized_title=excluded.normalized_title,
                alternate_titles=excluded.alternate_titles,
                normalized_alternate_titles=excluded.normalized_alternate_titles,
                folder=excluded.folder,
                -- Refresh ids too (a collection can be re-linked to a different
                -- TMDb id); otherwise a stale id breaks id-based matching.
                tmdb_id=excluded.tmdb_id,
                tvdb_id=excluded.tvdb_id,
                imdb_id=excluded.imdb_id
            """,
            (
                record.get("asset_type"),
                record.get("title"),
                record.get("normalized_title"),
                record.get("alternate_titles"),
                record.get("normalized_alternate_titles"),
                record.get("year"),
                record.get("tmdb_id"),
                record.get("tvdb_id"),
                record.get("imdb_id"),
                record.get("folder"),
                record.get("library_name"),
                record.get("instance_name"),
            ),
        )

    @staticmethod
    def _canonical_collection_key(item: dict) -> tuple:
        """Returns the unique key for collections_cache."""

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
            norm_str(item.get("library_name")),
            norm_str(item.get("instance_name")),
        )

    def get_by_instance(self, instance_name: str) -> list:
        """Return all collection rows for the given instance."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE instance_name=?",
                (instance_name,),
                fetch_all=True,
            )
            or []
        )

    def get_by_instance_and_library(
        self, instance_name: str, library_name: str
    ) -> list:
        """Return all collection rows for the given instance and library."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE instance_name=? AND library_name=?",
                (instance_name, library_name),
                fetch_all=True,
            )
            or []
        )

    def get_library_names_for_instance(self, instance_name: str) -> list:
        """Distinct library names present in the cache for an instance."""
        rows = self.execute_query(
            "SELECT DISTINCT library_name FROM collections_cache WHERE instance_name=?",
            (instance_name,),
            fetch_all=True,
        )
        return [r["library_name"] for r in (rows or []) if r["library_name"]]

    def get_by_id(self, id: int) -> Optional[dict]:
        """Return a single collection row by its unique integer ID."""
        return self.execute_query(
            "SELECT * FROM collections_cache WHERE id=?", (id,), fetch_one=True
        )

    def get_by_title_and_instance(
        self, title: str, instance_name: str, library_name: Optional[str] = None
    ) -> Optional[dict]:
        """Return one collection row for a title within an instance, or None."""
        # library_name is part of the unique key (see upsert's ON CONFLICT) —
        # `IS ?` so a None argument matches the NULL-library row.
        return self.execute_query(
            "SELECT * FROM collections_cache "
            "WHERE title=? AND instance_name=? AND library_name IS ?",
            (title, instance_name, library_name),
            fetch_one=True,
        )

    def get_all(self) -> list:
        """Return all records from collections_cache as a list of dicts."""
        return (
            self.execute_query("SELECT * FROM collections_cache", fetch_all=True) or []
        )

    def get_matched_with_files(self, limit: int) -> list:
        """Return up to `limit` matched rows that have a poster file.

        Bounded in SQL so preview-style callers never materialize the whole
        table for a handful of sample rows."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE matched=1 "
                "AND original_file IS NOT NULL AND original_file != '' LIMIT ?",
                (limit,),
                fetch_all=True,
            )
            or []
        )

    def get_unmatched(self) -> list:
        """Return all collections_cache records where matched=0."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE matched=0", fetch_all=True
            )
            or []
        )

    def reset_match_state(self) -> int:
        """Reset poster-match coverage to all-missing for collections the user
        hasn't curated. Mirrors MediaCache.reset_match_state — preserves
        ignored + user_confirmed (locked) rows. Returns rows reset."""
        predicate = (
            "(ignored IS NULL OR ignored = 0) "
            "AND (user_confirmed IS NULL OR user_confirmed = 0)"
        )
        # Scope COUNT and UPDATE identically (see MediaCache.reset_match_state):
        # include needs_review rows (status set, matched = 0), exclude
        # never-evaluated rows, so the count reflects rows actually cleared.
        scope = f"(matched = 1 OR match_status IS NOT NULL) AND {predicate}"
        row = self.execute_query(
            f"SELECT COUNT(*) AS n FROM collections_cache WHERE {scope}",
            fetch_one=True,
        )
        reset_count = int(row["n"]) if row else 0
        self.execute_query(
            "UPDATE collections_cache SET matched = 0, match_status = NULL, "
            "match_confidence = NULL, match_reason = NULL, "
            "matched_poster_file = NULL, matched_at = NULL "
            f"WHERE {scope}"
        )
        return reset_count

    def get_needs_review(self) -> list:
        """Return collections flagged for human review, excluding ignored."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache "
                "WHERE match_status='needs_review' "
                "AND (ignored IS NULL OR ignored=0)",
                fetch_all=True,
            )
            or []
        )

    def get_ignored(self) -> list:
        """Return collections the user has dismissed (ignored=1)."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE ignored=1", fetch_all=True
            )
            or []
        )

    def set_ignored(self, id: int, ignored: bool) -> None:
        """Toggle the user-dismissal flag for one collection row."""
        self.execute_query(
            "UPDATE collections_cache SET ignored=? WHERE id=?",
            (int(bool(ignored)), id),
        )

    def get_user_confirmed(self) -> list:
        """Return collections the user manually locked (user_confirmed=1)."""
        return (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE user_confirmed=1", fetch_all=True
            )
            or []
        )

    def set_user_confirmed(self, id: int, confirmed: bool) -> None:
        """Toggle the manual-pick lock for one collection row. While set,
        match_item leaves the row's match untouched on re-scans."""
        self.execute_query(
            "UPDATE collections_cache SET user_confirmed=? WHERE id=?",
            (int(bool(confirmed)), id),
        )

    def approve_match(self, id: int) -> None:
        """Promote one reviewed collection row to a full-confidence match."""
        self.execute_query(
            "UPDATE collections_cache SET match_status='matched', "
            "match_confidence=1.0, conflict_ids='[]' WHERE id=?",
            (id,),
        )

    def reopen_for_review(self, id: int) -> None:
        """Send one collection row back to the needs-review queue."""
        self.execute_query(
            "UPDATE collections_cache SET match_status='needs_review' WHERE id=?",
            (id,),
        )

    def set_match_provenance(
        self, id: int, matched_at: Optional[str], matched_poster_file: Optional[str]
    ) -> None:
        """Record (or clear, with None) when/what poster a collection matched.
        See media_cache.set_match_provenance for rationale."""
        self.execute_query(
            "UPDATE collections_cache SET matched_at=?, matched_poster_file=? "
            "WHERE id=?",
            (matched_at, matched_poster_file, id),
        )

    def clear(self) -> None:
        """Delete all rows from collections_cache."""
        self.execute_query("DELETE FROM collections_cache")

    def delete_by_id(self, id: int) -> None:
        """Delete a single record by its unique integer ID."""
        self.execute_query("DELETE FROM collections_cache WHERE id=?", (id,))

    def clear_library(self, instance_name: str, library_name: str) -> int:
        """Delete all cached collections for one (instance, library).

        Companion to plex_cache.clear_library: called on library opt-OUT so a
        de-selected library's collections stop surfacing. Returns rows deleted.
        """
        return self.execute_query(
            "DELETE FROM collections_cache WHERE instance_name=? AND library_name=?",
            (instance_name, library_name),
        )

    def delete(
        self, item: dict, instance_name: str, logger: Optional[Any] = None
    ) -> None:
        """Delete a single record by its unique key."""
        key_params = self._canonical_collection_key(
            {**item, "instance_name": instance_name}
        )
        sql = """
            DELETE FROM collections_cache
            WHERE title=? AND year IS ? AND tmdb_id IS ? AND tvdb_id IS ? AND imdb_id IS ? AND library_name IS ? AND instance_name=?
        """
        rows_deleted = self.execute_query(sql, key_params)
        if logger:
            logger.info(
                f"[DELETE] Collection Key: {key_params} | Rows deleted: {rows_deleted}"
            )

    def update(
        self,
        title: str,
        year: Optional[Any],
        library_name: Optional[str],
        instance_name: str,
        matched_value: Optional[Any] = None,
        original_file: Optional[Any] = None,
        renamed_file: Optional[Any] = None,
        file_hash: Optional[Any] = None,
        file_mtime: Optional[Any] = None,
        uploaded_libraries: Optional[Any] = None,
        source_file_hash: Optional[Any] = None,
        match_status: Optional[Any] = None,
        match_confidence: Optional[Any] = None,
        match_reason: Optional[Any] = None,
        ignored: Optional[Any] = None,
        conflict_ids: Optional[Any] = None,
        id: Optional[Any] = None,
    ) -> None:
        """Update fields for a given collection."""
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

        if source_file_hash is not None:
            set_clauses.append("source_file_hash=?")
            params.append(source_file_hash)

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

        if not set_clauses:
            return

        if id is not None:
            query = f"""
                UPDATE collections_cache
                SET {", ".join(set_clauses)}
                WHERE id=?
            """
            params.append(id)
            self.execute_query(query, tuple(params))
            return

        query = f"""
            UPDATE collections_cache
            SET {", ".join(set_clauses)}
            WHERE title=? AND instance_name=?
        """
        params.extend([title, instance_name])

        if year is None:
            query += " AND year IS NULL"
        else:
            query += " AND year=?"
            params.append(year)

        if library_name is None:
            query += " AND library_name IS NULL"
        else:
            query += " AND library_name=?"
            params.append(library_name)

        self.execute_query(query, tuple(params))

    def sync_collections_cache(
        self,
        instance_name: str,
        library_name: str,
        fresh_collections: list,
        logger=None,
    ):
        """
        Syncs the collections table for a specific instance to match fresh_collections.
        Removes missing, updates existing, adds new.
        """
        db_rows = (
            self.execute_query(
                "SELECT * FROM collections_cache WHERE instance_name=? AND library_name=?",
                (instance_name, library_name),
                fetch_all=True,
            )
            or []
        )

        db_map = {self._canonical_collection_key(row): row for row in db_rows}
        fresh_map = {
            self._canonical_collection_key(
                {**item, "instance_name": instance_name}
            ): item
            for item in fresh_collections
        }

        # Add/update items that are present in fresh_collections
        for key, item in fresh_map.items():
            self.upsert(item, instance_name)
            if key not in db_map and logger:
                logger.debug(
                    f"[ADD] New collection '{item['title']}' for {instance_name}"
                )

        # Remove items that are no longer present
        keys_to_remove = set(db_map.keys()) - set(fresh_map.keys())
        for key in keys_to_remove:
            row = db_map[key]
            self.delete(row, instance_name, logger)

        if logger:
            logger.debug(
                f"[SYNC] Collections table for {instance_name} synchronized. {len(fresh_collections)} items present."
            )
