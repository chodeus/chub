# util/database/media_asset_matches.py

from datetime import datetime, timezone
from typing import List, Optional

from .db_base import DatabaseBase


class MediaAssetMatches(DatabaseBase):
    """Per-(media, image_type) provenance for the additional asset types
    (logo / squareart / background / banner).

    Kept separate from ``media_cache.matched_poster_file`` (the poster's single
    matched-file state) so a media item can independently carry each asset type.
    A row is keyed by ``(target_kind, target_id, image_type)`` where target_kind
    is "media" (media_cache.id) or "collection" (collections_cache.id).
    """

    def upsert(
        self,
        *,
        target_kind: str,
        target_id: int,
        image_type: str,
        source: Optional[str] = None,
        matched_file: Optional[str] = None,
        matched_url: Optional[str] = None,
        source_mtime: Optional[float] = None,
        applied_method: Optional[str] = None,
        applied_path: Optional[str] = None,
        applied_libraries: Optional[str] = None,
        match_status: Optional[str] = None,
        detail: Optional[str] = None,
        matched_at: Optional[str] = None,
    ) -> None:
        """Insert or refresh the match row for one (target, image_type)."""
        matched_at = matched_at or datetime.now(timezone.utc).isoformat()
        self.execute_query(
            """
            INSERT INTO media_asset_matches
                (target_kind, target_id, image_type, source, matched_file,
                 matched_url, source_mtime, applied_method, applied_path,
                 applied_libraries, match_status, detail, matched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_kind, target_id, image_type)
            DO UPDATE SET
                source=excluded.source,
                matched_file=excluded.matched_file,
                matched_url=excluded.matched_url,
                source_mtime=excluded.source_mtime,
                applied_method=excluded.applied_method,
                applied_path=excluded.applied_path,
                applied_libraries=excluded.applied_libraries,
                match_status=excluded.match_status,
                detail=excluded.detail,
                matched_at=excluded.matched_at
            """,
            (
                target_kind,
                int(target_id),
                image_type,
                source,
                matched_file,
                matched_url,
                source_mtime,
                applied_method,
                applied_path,
                applied_libraries,
                match_status,
                detail,
                matched_at,
            ),
        )

    def set_ignored(
        self, target_kind: str, target_id: int, image_type: str, ignored: bool
    ) -> None:
        """Set the per-(target, image_type) "not needed" flag.

        Works even when no match row exists yet — a *missing* asset has no row,
        so ignoring it inserts a status-less row carrying just the flag. An
        existing row keeps its match provenance and only flips ``ignored``.
        """
        self.execute_query(
            """
            INSERT INTO media_asset_matches
                (target_kind, target_id, image_type, matched_at, ignored)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(target_kind, target_id, image_type)
            DO UPDATE SET ignored=excluded.ignored
            """,
            (
                target_kind,
                int(target_id),
                image_type,
                datetime.now(timezone.utc).isoformat(),
                1 if ignored else 0,
            ),
        )

    def set_user_confirmed(
        self, target_kind: str, target_id: int, image_type: str, confirmed: bool
    ) -> None:
        """Set the per-(target, image_type) manual-pick lock.

        Mirrors ``set_ignored``: works even with no prior match row (inserts a
        status-less row carrying just the flag), and an existing row keeps its
        match provenance — only ``user_confirmed`` flips. A locked row is reused
        verbatim by the asset run instead of being re-resolved.
        """
        self.execute_query(
            """
            INSERT INTO media_asset_matches
                (target_kind, target_id, image_type, matched_at, user_confirmed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(target_kind, target_id, image_type)
            DO UPDATE SET user_confirmed=excluded.user_confirmed
            """,
            (
                target_kind,
                int(target_id),
                image_type,
                datetime.now(timezone.utc).isoformat(),
                1 if confirmed else 0,
            ),
        )

    def get_one(
        self, target_kind: str, target_id: int, image_type: str
    ) -> Optional[dict]:
        """Return the single match row for one (target, image_type), or None."""
        row = self.execute_query(
            "SELECT * FROM media_asset_matches "
            "WHERE target_kind=? AND target_id=? AND image_type=?",
            (target_kind, int(target_id), image_type),
            fetch_one=True,
        )
        return dict(row) if row else None

    def get_for_target(self, target_kind: str, target_id: int) -> List[dict]:
        """Return all asset-match rows for one media/collection target."""
        rows = (
            self.execute_query(
                "SELECT * FROM media_asset_matches WHERE target_kind=? AND target_id=?",
                (target_kind, int(target_id)),
                fetch_all=True,
            )
            or []
        )
        return [dict(r) for r in rows]

    def get_by_type(self, image_type: str) -> List[dict]:
        """Return all match rows for a given image_type."""
        rows = (
            self.execute_query(
                "SELECT * FROM media_asset_matches WHERE image_type=?",
                (image_type,),
                fetch_all=True,
            )
            or []
        )
        return [dict(r) for r in rows]

    def get_all(self) -> List[dict]:
        rows = (
            self.execute_query("SELECT * FROM media_asset_matches", fetch_all=True)
            or []
        )
        return [dict(r) for r in rows]

    def purge_season_logos(self) -> int:
        """Delete logo rows whose target is a season row of a show.

        Clear logos are show-level only: providers (TMDB / fanart.tv) publish no
        per-season logos, so a season+logo row — typically "missing" — can never
        be satisfied automatically and only skews the Unmatched artwork coverage.
        asset_renamerr calls this at the start of each run so databases written
        by older versions (which recorded those rows) self-heal. Returns the
        number of rows deleted.
        """
        deleted = self.execute_query(
            "DELETE FROM media_asset_matches "
            "WHERE image_type = 'logo' AND target_kind = 'media' "
            "AND target_id IN (SELECT id FROM media_cache "
            "WHERE asset_type = 'show' AND season_number IS NOT NULL)"
        )
        return int(deleted or 0)

    def clear(self, keep_ignored: bool = False) -> int:
        """Delete artwork-match rows; returns rows deleted."""
        # keep_ignored preserves the user's intent rows: ignored=1 AND
        # user_confirmed=1 (the reset must honour locked picks).
        if keep_ignored:
            deleted = self.execute_query(
                "DELETE FROM media_asset_matches "
                "WHERE (ignored IS NULL OR ignored = 0) "
                "AND (user_confirmed IS NULL OR user_confirmed = 0)"
            )
        else:
            deleted = self.execute_query("DELETE FROM media_asset_matches")
        return int(deleted or 0)
