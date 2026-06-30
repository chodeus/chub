# util/database/schema.py

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class ColumnDefinition:
    """Represents a database column definition."""

    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: Optional[str] = None
    default: Optional[Any] = None
    unique: bool = False
    check_constraint: Optional[str] = None

    def to_sql(self) -> str:
        """Convert column definition to SQL DDL."""
        sql = f"{self.name} {self.type}"

        if self.primary_key:
            sql += " PRIMARY KEY"
            if self.type.upper() == "INTEGER":
                sql += " AUTOINCREMENT"

        if not self.nullable:
            sql += " NOT NULL"

        if self.default is not None:
            if isinstance(self.default, str) and self.default != "CURRENT_TIMESTAMP":
                sql += f" DEFAULT '{self.default}'"
            else:
                sql += f" DEFAULT {self.default}"

        if self.unique:
            sql += " UNIQUE"

        if self.check_constraint:
            sql += f" CHECK ({self.check_constraint})"

        if self.foreign_key:
            sql += f" REFERENCES {self.foreign_key}"

        return sql

    def to_add_column_sql(self) -> str:
        """Column clause valid for ``ALTER TABLE ... ADD COLUMN``.

        SQLite rejects UNIQUE, PRIMARY KEY, and non-constant DEFAULT (e.g.
        CURRENT_TIMESTAMP) on ADD COLUMN, and only allows NOT NULL when a
        constant default is supplied. Emit only what ADD COLUMN accepts;
        uniqueness is recreated via a separate CREATE UNIQUE INDEX in
        add_missing_columns so the constraint isn't silently lost.
        """
        sql = f"{self.name} {self.type}"
        has_constant_default = self.default is not None and not (
            isinstance(self.default, str) and self.default == "CURRENT_TIMESTAMP"
        )
        if not self.nullable and has_constant_default:
            sql += " NOT NULL"
        if has_constant_default:
            if isinstance(self.default, str):
                sql += f" DEFAULT '{self.default}'"
            else:
                sql += f" DEFAULT {self.default}"
        if self.check_constraint:
            sql += f" CHECK ({self.check_constraint})"
        if self.foreign_key:
            sql += f" REFERENCES {self.foreign_key}"
        return sql


@dataclass
class TableDefinition:
    """Represents a database table definition."""

    name: str
    columns: List[ColumnDefinition] = field(default_factory=list)
    indexes: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    def get_column(self, name: str) -> Optional[ColumnDefinition]:
        """Get column definition by name."""
        return next((col for col in self.columns if col.name == name), None)

    def to_create_sql(self) -> str:
        """Generate CREATE TABLE SQL."""
        columns_sql = [col.to_sql() for col in self.columns]

        # Add table-level constraints
        for constraint in self.constraints:
            columns_sql.append(constraint)

        joined_columns = ",\n            ".join(columns_sql)
        return (
            f"CREATE TABLE IF NOT EXISTS {self.name} (\n"
            f"            {joined_columns}\n"
            f"        )"
        )


class SchemaManager:
    """Enhanced schema manager with automatic column management and change tracking."""

    def __init__(self):
        self.tables: Dict[str, TableDefinition] = {}
        self._schema_hash: Optional[str] = None
        self._define_schema()

    def _define_schema(self) -> None:
        """Define the complete CHUB database schema using structured definitions."""

        # Plex Media Cache
        plex_media_cache = TableDefinition(
            name="plex_media_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("plex_id", "TEXT", nullable=False),
                ColumnDefinition("instance_name", "TEXT", nullable=False),
                ColumnDefinition("asset_type", "TEXT"),
                ColumnDefinition("library_name", "TEXT"),
                ColumnDefinition("title", "TEXT"),
                ColumnDefinition("normalized_title", "TEXT"),
                # Parent linkage for music albums: the owning artist's title.
                # NULL for movies/shows/artists. Lets album rows resolve against
                # the parent-scoped match keys ("{parent_norm}::{album_norm}").
                ColumnDefinition("parent_title", "TEXT"),
                ColumnDefinition("parent_normalized_title", "TEXT"),
                ColumnDefinition("season_number", "INTEGER"),
                ColumnDefinition("year", "TEXT"),
                ColumnDefinition("guids", "TEXT"),
                ColumnDefinition("labels", "TEXT"),
                ColumnDefinition("file_paths", "TEXT"),
                # Stamped on every upsert; lets callers judge cache freshness
                # (TTL guard) before deciding to re-walk Plex. Additive default
                # so it auto-migrates on existing databases.
                ColumnDefinition("updated_at", "TEXT", default="CURRENT_TIMESTAMP"),
            ],
            constraints=["UNIQUE (plex_id, instance_name)"],
        )
        self._add_table(plex_media_cache)

        # Media Cache - Enhanced with advanced search filtering fields
        media_cache = TableDefinition(
            name="media_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("identity_key", "TEXT", nullable=False, unique=True),
                ColumnDefinition("asset_type", "TEXT"),
                ColumnDefinition("title", "TEXT"),
                ColumnDefinition("normalized_title", "TEXT"),
                ColumnDefinition("alternate_titles", "TEXT"),
                ColumnDefinition("normalized_alternate_titles", "TEXT"),
                ColumnDefinition("year", "TEXT"),
                ColumnDefinition("tmdb_id", "INTEGER"),
                ColumnDefinition("tvdb_id", "INTEGER"),
                ColumnDefinition("imdb_id", "TEXT"),
                ColumnDefinition("musicbrainz_id", "TEXT"),
                # Parent linkage for music albums (asset_type="album"): the
                # owning artist's MusicBrainz ID and title. NULL for every other
                # asset type. Used to scope album match keys under their artist
                # so identically-named albums ("Greatest Hits") don't collide.
                ColumnDefinition("parent_musicbrainz_id", "TEXT"),
                ColumnDefinition("parent_title", "TEXT"),
                ColumnDefinition("folder", "TEXT"),
                ColumnDefinition("root_folder", "TEXT"),
                ColumnDefinition(
                    "media_file", "TEXT"
                ),  # Media filename from the *arr (Radarr movieFile.relativePath)
                ColumnDefinition("tags", "TEXT"),
                ColumnDefinition("season_number", "INTEGER"),
                ColumnDefinition("matched", "BOOLEAN"),
                ColumnDefinition("instance_name", "TEXT"),
                ColumnDefinition("source", "TEXT"),
                ColumnDefinition("original_file", "TEXT"),
                ColumnDefinition("renamed_file", "TEXT"),
                ColumnDefinition("file_hash", "TEXT"),
                ColumnDefinition("poster_url", "TEXT"),
                ColumnDefinition(
                    "arr_id", "INTEGER"
                ),  # ARR media ID for direct API operations
                ColumnDefinition(
                    "plex_mapping_id", "INTEGER"
                ),  # Foreign key to plex_media_cache.id
                # Advanced search filtering fields
                ColumnDefinition(
                    "status", "TEXT"
                ),  # available, missing, downloading, etc.
                ColumnDefinition(
                    "rating", "TEXT"
                ),  # Content rating (PG, R, TV-MA, etc.)
                ColumnDefinition("studio", "TEXT"),  # Production studio/network
                ColumnDefinition(
                    "edition", "TEXT"
                ),  # Edition info (Director's Cut, etc.)
                ColumnDefinition("runtime", "INTEGER"),  # Duration in minutes
                ColumnDefinition(
                    "language", "TEXT"
                ),  # Original language (en, fr, etc.)
                ColumnDefinition(
                    "monitored", "BOOLEAN", default=1
                ),  # Whether item is monitored
                ColumnDefinition(
                    "has_content", "BOOLEAN"
                ),  # Movie: hasFile. Season: episodeCount > 0. Used to hide
                # unreleased/undownloaded items from unmatched-asset reports.
                # No default — rows that predate this column read as NULL
                # and rely on the *arr `status` field as a fallback gate.
                ColumnDefinition("genre", "TEXT"),  # JSON array of genres
                ColumnDefinition(
                    "release_date", "TEXT"
                ),  # ISO date (YYYY-MM-DD) — Lidarr album release date; gates
                # "missing" vs "upcoming" in Library Statistics. NULL = treat
                # as released (pre-column rows / non-album types).
                # Per-season episode unit counts (Sonarr) for episode-level stats:
                # downloaded / aired / total. NULL for non-season rows.
                ColumnDefinition("episode_files", "INTEGER"),
                ColumnDefinition("aired_episodes", "INTEGER"),
                ColumnDefinition("total_episodes", "INTEGER"),
                ColumnDefinition(
                    "created_at", "TEXT"
                ),  # ISO timestamp when item was first cached
                # --- Match transparency / lifecycle ---
                # match_status is the tri-state the UI surfaces:
                #   "matched"      — a poster was confidently linked
                #   "needs_review" — a weak/ambiguous/unverified candidate
                #                     exists; a human should confirm it
                #   "unmatched"    — nothing found
                # It is independent of the transient `matched` flag (which the
                # rename phase clears), so the review/ignore UI survives a
                # rename pass.
                ColumnDefinition("match_status", "TEXT"),
                # 0.0–1.0 confidence from the match tier (ID=high, exact
                # title+year=high, normalized title=medium, loose/fuzzy=low).
                ColumnDefinition("match_confidence", "REAL"),
                # Human-readable explanation from is_match() (previously
                # computed then discarded) — e.g. "ID match: tmdb_id".
                ColumnDefinition("match_reason", "TEXT"),
                # User dismissal: ignored rows are hidden from unmatched/review
                # reports and never re-surfaced.
                ColumnDefinition("ignored", "BOOLEAN", default=0),
                # JSON array of competing candidate descriptors when two+ posters
                # match with conflicting IDs — drives the "needs_review" state.
                ColumnDefinition("conflict_ids", "TEXT"),
                # JSON array of {old, new, at} entries appended each rename.
                ColumnDefinition("rename_history", "TEXT"),
                # ISO timestamp of the most recent *new or changed* poster
                # match (not re-stamped when an existing match is re-confirmed),
                # plus the source poster file it matched. Powers the
                # "Recently matched" reel — linking by file (not poster_cache.id)
                # so it survives the cache's clear-and-reinsert on every scan.
                ColumnDefinition("matched_at", "TEXT"),
                ColumnDefinition("matched_poster_file", "TEXT"),
                # Set when a user manually applies/approves a poster. While set,
                # match_item leaves the row's match state untouched on re-scans
                # so a scheduled poster_renamerr run can never revert the manual
                # pick. Cleared if the user re-opens it for review. Defaults 0.
                ColumnDefinition("user_confirmed", "BOOLEAN", default=0),
                # mtime of the matched poster file at last successful upload. A
                # single os.stat() against this skips the sha256 read when the
                # file is unchanged (page-cache-friendly fast path). Paired with
                # file_hash, which remains the authority when mtime differs.
                ColumnDefinition("file_mtime", "REAL"),
                # JSON list of Plex library names this poster's current hash has
                # been uploaded to. A title can live in several enabled libraries
                # on one server (e.g. an HD and a 4K library); the "skip if
                # unchanged" check is per-library, not per-file, so a newly-added
                # library copy is backfilled on the next run without forcing.
                ColumnDefinition("uploaded_libraries", "TEXT"),
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS media_cache_plex_mapping_idx ON media_cache (plex_mapping_id)",
                "CREATE INDEX IF NOT EXISTS media_cache_match_status_idx ON media_cache (match_status)",
                "CREATE INDEX IF NOT EXISTS media_cache_ignored_idx ON media_cache (ignored)",
                "CREATE INDEX IF NOT EXISTS media_cache_matched_at_idx ON media_cache (matched_at)",
                "CREATE INDEX IF NOT EXISTS media_cache_instance_idx ON media_cache (instance_name)",
                # Composite for sync_for_instance / clear_by_instance_and_type,
                # which filter on (instance_name, asset_type) together.
                "CREATE INDEX IF NOT EXISTS media_cache_instance_type_idx ON media_cache (instance_name, asset_type)",
                # Advanced search filtering indexes
                "CREATE INDEX IF NOT EXISTS media_cache_status_idx ON media_cache (status)",
                "CREATE INDEX IF NOT EXISTS media_cache_rating_idx ON media_cache (rating)",
                "CREATE INDEX IF NOT EXISTS media_cache_studio_idx ON media_cache (studio)",
                "CREATE INDEX IF NOT EXISTS media_cache_runtime_idx ON media_cache (runtime)",
                "CREATE INDEX IF NOT EXISTS media_cache_language_idx ON media_cache (language)",
                "CREATE INDEX IF NOT EXISTS media_cache_monitored_idx ON media_cache (monitored)",
            ],
        )
        self._add_table(media_cache)

        # Collections Cache
        collections_cache = TableDefinition(
            name="collections_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("asset_type", "TEXT"),
                ColumnDefinition("title", "TEXT"),
                ColumnDefinition("normalized_title", "TEXT"),
                ColumnDefinition("alternate_titles", "TEXT"),
                ColumnDefinition("normalized_alternate_titles", "TEXT"),
                ColumnDefinition("year", "INTEGER"),
                ColumnDefinition("tmdb_id", "INTEGER"),
                ColumnDefinition("tvdb_id", "INTEGER"),
                ColumnDefinition("imdb_id", "TEXT"),
                ColumnDefinition("folder", "TEXT"),
                ColumnDefinition("library_name", "TEXT"),
                ColumnDefinition("instance_name", "TEXT"),
                ColumnDefinition("matched", "INTEGER", default=0),
                ColumnDefinition("original_file", "TEXT"),
                ColumnDefinition("renamed_file", "TEXT"),
                # Match transparency / lifecycle — mirrors media_cache. See the
                # media_cache definition above for column semantics.
                ColumnDefinition("match_status", "TEXT"),
                ColumnDefinition("match_confidence", "REAL"),
                ColumnDefinition("match_reason", "TEXT"),
                ColumnDefinition("ignored", "BOOLEAN", default=0),
                ColumnDefinition("conflict_ids", "TEXT"),
                ColumnDefinition("matched_at", "TEXT"),
                ColumnDefinition("matched_poster_file", "TEXT"),
                # See media_cache.user_confirmed — manual-pick lock that match
                # re-scans must respect.
                ColumnDefinition("user_confirmed", "BOOLEAN", default=0),
                # See media_cache.file_mtime — sha256 fast-path.
                ColumnDefinition("file_hash", "TEXT"),
                ColumnDefinition("file_mtime", "REAL"),
                # See media_cache.uploaded_libraries — per-library upload record.
                ColumnDefinition("uploaded_libraries", "TEXT"),
            ],
            constraints=["UNIQUE (title, library_name, instance_name)"],
        )
        self._add_table(collections_cache)

        # Google Drive Stats
        gdrive_stats = TableDefinition(
            name="gdrive_stats",
            columns=[
                ColumnDefinition("location", "TEXT", primary_key=True, nullable=False),
                ColumnDefinition("owner", "TEXT"),
                ColumnDefinition("folder_name", "TEXT"),
                ColumnDefinition("file_count", "INTEGER"),
                ColumnDefinition("size_bytes", "INTEGER"),
                ColumnDefinition("last_updated", "TEXT"),
            ],
        )
        self._add_table(gdrive_stats)

        # Orphaned Posters
        # Poster Collections
        poster_collections = TableDefinition(
            name="poster_collections",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("name", "TEXT", nullable=False),
                ColumnDefinition("description", "TEXT"),
                ColumnDefinition("created_at", "TEXT"),
            ],
        )
        self._add_table(poster_collections)

        # Poster Collection Items
        poster_collection_items = TableDefinition(
            name="poster_collection_items",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("collection_id", "INTEGER", nullable=False),
                ColumnDefinition("poster_id", "INTEGER", nullable=False),
            ],
            constraints=["UNIQUE(collection_id, poster_id)"],
        )
        self._add_table(poster_collection_items)

        # Poster Cache
        poster_cache = TableDefinition(
            name="poster_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("asset_type", "TEXT"),
                ColumnDefinition("title", "TEXT"),
                ColumnDefinition("normalized_title", "TEXT"),
                ColumnDefinition("year", "INTEGER"),
                ColumnDefinition("tmdb_id", "INTEGER"),
                ColumnDefinition("tvdb_id", "INTEGER"),
                ColumnDefinition("imdb_id", "TEXT"),
                # MusicBrainz id of a music source poster (artist/album), plus
                # parent linkage for albums. NULL for non-music posters. Lets a
                # music cover match its media row by MBID first (is_match /
                # find_asset_candidate), then by parent-scoped title.
                ColumnDefinition("musicbrainz_id", "TEXT"),
                ColumnDefinition("parent_musicbrainz_id", "TEXT"),
                ColumnDefinition("parent_title", "TEXT"),
                ColumnDefinition("parent_normalized_title", "TEXT"),
                ColumnDefinition("season_number", "INTEGER"),
                ColumnDefinition("folder", "TEXT"),
                ColumnDefinition("file", "TEXT"),
                # Style prefix derived from the matching gdrive_list entry's
                # name (e.g. "CL2K Solen" -> "CL2K"). NULL if the source dir
                # didn't match any configured gdrive entry.
                ColumnDefinition("style", "TEXT"),
                # Backfilled lazily (on first read) by the posters API —
                # populated via PIL.Image.open so there's no extra
                # scan-all-posters migration step.
                ColumnDefinition("width", "INTEGER"),
                ColumnDefinition("height", "INTEGER"),
                ColumnDefinition("created_at", "TEXT"),
                # Source-dir bottom-wins priority. Stamped at merge time from
                # the asset's source_dir index in poster_renamerr.source_dirs
                # (higher = later in list = wins). The match-phase queries
                # ORDER BY this DESC so the bottom source_dir's row is
                # returned first. See poster_cache.py CONTRACT block and
                # tests/test_poster_renamerr.py::test_source_dirs_bottom_wins.
                ColumnDefinition("priority", "INTEGER", default=0),
                # Distinguishes plain posters from the additional asset types
                # (logo/squareart/background/banner) that share this table.
                # Defaults to "poster"; legacy rows back-fill to "poster" via
                # this DEFAULT. The poster matcher + poster UI queries filter on
                # image_type="poster" so assets never leak into poster flows.
                # See backend/modules/asset_renamerr.py.
                ColumnDefinition("image_type", "TEXT", default="poster"),
                # Search-only rows are indexed for Assets Search but excluded
                # from poster matching/apply. Set on assets that live under a
                # gdrive_list location not covered by a poster_renamerr/
                # asset_renamerr source_dir (e.g. an "Extras" drive the user
                # hasn't wired into a renamer). Defaults to 0 so every existing
                # row and every source_dir asset stays fully matchable. The
                # match-phase queries filter search_only=0.
                ColumnDefinition("search_only", "INTEGER", default=0),
            ],
            constraints=[
                "UNIQUE(title, year, tmdb_id, tvdb_id, imdb_id, season_number, file)"
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS poster_cache_normalized_title_idx ON poster_cache (normalized_title)",
                "CREATE INDEX IF NOT EXISTS poster_cache_tmdb_id_idx ON poster_cache (tmdb_id)",
                "CREATE INDEX IF NOT EXISTS poster_cache_tvdb_id_idx ON poster_cache (tvdb_id)",
                "CREATE INDEX IF NOT EXISTS poster_cache_imdb_id_idx ON poster_cache (imdb_id)",
                "CREATE INDEX IF NOT EXISTS poster_cache_asset_type_idx ON poster_cache (asset_type)",
                "CREATE INDEX IF NOT EXISTS poster_cache_style_idx ON poster_cache (style)",
                "CREATE INDEX IF NOT EXISTS poster_cache_created_at_idx ON poster_cache (created_at)",
                "CREATE INDEX IF NOT EXISTS poster_cache_resolution_idx ON poster_cache (width, height)",
                "CREATE INDEX IF NOT EXISTS poster_cache_image_type_idx ON poster_cache (image_type)",
                "CREATE INDEX IF NOT EXISTS poster_cache_search_only_idx ON poster_cache (search_only)",
            ],
        )
        self._add_table(poster_cache)

        # Per-(media, image_type) asset match/apply provenance. Kept separate
        # from media_cache.matched_poster_file (which is the poster's single-file
        # state) so a media item can carry a logo + squareart + background +
        # banner independently without disturbing poster matching.
        media_asset_matches = TableDefinition(
            name="media_asset_matches",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                # target_kind + target_id identify the matched row:
                #   "media"      -> media_cache.id
                #   "collection" -> collections_cache.id
                # A (kind, id) pair instead of two nullable FK columns so the
                # UNIQUE below actually enforces (SQLite treats NULLs in a
                # UNIQUE as distinct, which would defeat ON CONFLICT upserts).
                ColumnDefinition("target_kind", "TEXT", nullable=False),
                ColumnDefinition("target_id", "INTEGER", nullable=False),
                # logo | squareart | background | banner
                ColumnDefinition("image_type", "TEXT", nullable=False),
                # local | tmdb — which source won the priority resolution.
                ColumnDefinition("source", "TEXT"),
                ColumnDefinition("matched_file", "TEXT"),  # local source file path
                ColumnDefinition("matched_url", "TEXT"),  # tmdb image URL
                # mtime of matched_file at last apply — lets a re-run skip an
                # unchanged local asset without re-uploading/re-copying it.
                ColumnDefinition("source_mtime", "REAL"),
                ColumnDefinition("applied_method", "TEXT"),  # direct | kometa
                ColumnDefinition("applied_path", "TEXT"),  # kometa destination written
                # JSON list of "instance/library" keys this asset was uploaded
                # to on the direct path — so a re-run backfills a newly-added or
                # previously-failed library copy instead of skipping the item
                # because the source is unchanged (mirrors the poster
                # uploaded_libraries column). NULL for the library-agnostic
                # kometa path.
                ColumnDefinition("applied_libraries", "TEXT"),
                ColumnDefinition("match_status", "TEXT"),
                # Human-readable outcome detail — on success the applied
                # path/libraries summary, on failure WHY it failed (so the
                # Needs-Review view can explain itself instead of just saying
                # "failed"). Additive default NULL; auto-migrates.
                ColumnDefinition("detail", "TEXT"),
                ColumnDefinition("matched_at", "TEXT"),
                # Per-(media, image_type) "not needed" flag set from the
                # Unmatched → Additional artwork view, so a user can dismiss a
                # missing logo while still tracking a missing background. The
                # asset run skips ignored (media, type) pairs. Additive default
                # 0 so it auto-migrates on existing databases.
                ColumnDefinition("ignored", "INTEGER", default=0),
                # Manual-pick lock: 1 when the user explicitly chose this
                # artwork file in the picker. A locked (media, image_type) is
                # reused verbatim on re-runs (the matcher won't re-resolve or
                # overwrite it) until the user unlocks it — mirrors
                # media_cache.user_confirmed for posters. Additive default 0 so
                # it auto-migrates on existing databases.
                ColumnDefinition("user_confirmed", "INTEGER", default=0),
            ],
            constraints=["UNIQUE(target_kind, target_id, image_type)"],
            indexes=[
                "CREATE INDEX IF NOT EXISTS maa_target_idx ON media_asset_matches (target_kind, target_id)",
                "CREATE INDEX IF NOT EXISTS maa_type_idx ON media_asset_matches (image_type)",
            ],
        )
        self._add_table(media_asset_matches)

        # Holiday Status
        holiday_status = TableDefinition(
            name="holiday_status",
            columns=[
                ColumnDefinition(
                    "id",
                    "INTEGER",
                    primary_key=True,
                    nullable=False,
                    check_constraint="id = 1",
                ),
                ColumnDefinition("last_active_holiday", "TEXT"),
            ],
        )
        self._add_table(holiday_status)

        border_state = TableDefinition(
            name="border_state",
            columns=[
                ColumnDefinition(
                    "renamed_file", "TEXT", primary_key=True, nullable=False
                ),
                ColumnDefinition("source_mtime", "REAL"),
                ColumnDefinition("source_size", "INTEGER"),
                ColumnDefinition("variant_sig", "TEXT"),
                ColumnDefinition("updated_at", "TEXT"),
            ],
        )
        self._add_table(border_state)

        # Run State
        run_state = TableDefinition(
            name="run_state",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("module_name", "TEXT", nullable=False, unique=True),
                ColumnDefinition("last_run", "TEXT"),
                ColumnDefinition("last_run_successful", "INTEGER", default=0),
                ColumnDefinition("last_run_status", "TEXT"),
                ColumnDefinition("last_run_message", "TEXT"),
                ColumnDefinition("last_duration", "INTEGER"),
                ColumnDefinition("last_run_by", "TEXT"),
            ],
        )
        self._add_table(run_state)

        # Jobs
        jobs = TableDefinition(
            name="jobs",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("type", "TEXT", nullable=False),
                ColumnDefinition("received_at", "TEXT"),
                ColumnDefinition("payload", "TEXT"),
                ColumnDefinition("status", "TEXT", default="pending"),
                ColumnDefinition("result", "TEXT"),
                ColumnDefinition("error", "TEXT"),
                ColumnDefinition("attempts", "INTEGER", default=0),
                ColumnDefinition("max_attempts", "INTEGER", default=3),
                ColumnDefinition("scheduled_at", "TEXT"),
                ColumnDefinition("priority", "INTEGER", default=0),
                ColumnDefinition("progress", "INTEGER", default=0),
                # phases: JSON array of per-sub-step records
                # [{name, status, started_at, finished_at, duration_s}], written
                # by orchestrating modules (poster_renamerr, asset_renamerr) so
                # the Jobs page can show each pipeline phase and its timing.
                ColumnDefinition("phases", "TEXT"),
                ColumnDefinition("started_at", "TEXT"),
                ColumnDefinition("completed_at", "TEXT"),
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status)",
                "CREATE INDEX IF NOT EXISTS jobs_type_idx ON jobs(type)",
                "CREATE INDEX IF NOT EXISTS jobs_priority_idx ON jobs(priority, status)",
                "CREATE INDEX IF NOT EXISTS jobs_scheduled_idx ON jobs(scheduled_at)",
            ],
        )
        self._add_table(jobs)

        # Scan cache — persists scan results (e.g. nestarr) across page navigations
        scan_cache = TableDefinition(
            name="scan_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("scan_type", "TEXT", nullable=False, unique=True),
                ColumnDefinition("data", "TEXT"),
                ColumnDefinition("scanned_at", "TEXT"),
            ],
        )
        self._add_table(scan_cache)

        # System health snapshots — periodic instance probes written by the
        # scheduler so the dashboard and digest endpoints have historical data
        # without forcing live probes on every render.
        system_health_snapshots = TableDefinition(
            name="system_health_snapshots",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("snapshot_at", "TEXT", nullable=False),
                ColumnDefinition("service", "TEXT"),
                ColumnDefinition("instance_name", "TEXT"),
                ColumnDefinition("status", "TEXT"),
                ColumnDefinition("status_code", "INTEGER"),
                ColumnDefinition("response_time_ms", "INTEGER"),
                ColumnDefinition("error", "TEXT"),
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS system_health_time_idx ON system_health_snapshots (snapshot_at)",
                "CREATE INDEX IF NOT EXISTS system_health_instance_idx ON system_health_snapshots (instance_name, snapshot_at)",
            ],
        )
        self._add_table(system_health_snapshots)

        # Webhook dedup cache — persistent rolling window so Sonarr/Radarr
        # retries (minutes apart) get coalesced even across restarts.
        # UNIQUE on (item_type, item_name) with timestamp-based eviction
        # handled by the WebhookCache interface.
        webhook_cache = TableDefinition(
            name="webhook_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("item_type", "TEXT", nullable=False),
                ColumnDefinition("item_name", "TEXT", nullable=False),
                ColumnDefinition(
                    "timestamp", "TEXT", nullable=False, default="CURRENT_TIMESTAMP"
                ),
            ],
            constraints=[
                "UNIQUE (item_type, item_name)",
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS webhook_cache_timestamp_idx ON webhook_cache (timestamp)",
            ],
        )
        self._add_table(webhook_cache)

        # Media edit history — audit trail for user-initiated metadata edits.
        media_edit_history = TableDefinition(
            name="media_edit_history",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("media_id", "INTEGER", nullable=False),
                ColumnDefinition("edited_at", "TEXT", nullable=False),
                ColumnDefinition("edited_by", "TEXT"),
                ColumnDefinition("field", "TEXT", nullable=False),
                ColumnDefinition("old_value", "TEXT"),
                ColumnDefinition("new_value", "TEXT"),
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS media_edit_history_media_idx ON media_edit_history (media_id, edited_at)",
                "CREATE INDEX IF NOT EXISTS media_edit_history_time_idx ON media_edit_history (edited_at)",
            ],
        )
        self._add_table(media_edit_history)

        # Upgradinatorr progress — tracks searched seasons/albums in season_album
        # count_mode so rotations can resume mid-series/artist instead of
        # re-searching the same children on every run.
        upgradinatorr_progress = TableDefinition(
            name="upgradinatorr_progress",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("instance_name", "TEXT", nullable=False),
                ColumnDefinition("media_id", "INTEGER", nullable=False),
                ColumnDefinition("child_id", "TEXT", nullable=False),
                ColumnDefinition("searched_at", "TEXT"),
            ],
            indexes=[
                "CREATE UNIQUE INDEX IF NOT EXISTS upgradinatorr_progress_unique_idx ON upgradinatorr_progress (instance_name, media_id, child_id)",
                "CREATE INDEX IF NOT EXISTS upgradinatorr_progress_lookup_idx ON upgradinatorr_progress (instance_name, media_id)",
            ],
        )
        self._add_table(upgradinatorr_progress)

        # TMDB external-ID lookup cache — maps (tvdb_id|imdb_id, media_type)
        # → tmdb_id resolved via TMDB's /3/find endpoint. Negative-cache rows
        # (tmdb_id NULL) prevent re-querying known-missing IDs. Expiration is
        # enforced in the TMDBClient code, not by SQL. Critical for staying
        # within TMDB's rate limits across repeated syncs.
        tmdb_id_cache = TableDefinition(
            name="tmdb_id_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("external_id", "TEXT", nullable=False),
                ColumnDefinition("source", "TEXT", nullable=False),
                ColumnDefinition("media_type", "TEXT", nullable=False),
                ColumnDefinition("tmdb_id", "INTEGER"),
                ColumnDefinition(
                    "cached_at", "TEXT", nullable=False, default="CURRENT_TIMESTAMP"
                ),
            ],
            constraints=[
                "UNIQUE (external_id, source, media_type)",
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS tmdb_id_cache_lookup_idx ON tmdb_id_cache (external_id, source, media_type)",
            ],
        )
        self._add_table(tmdb_id_cache)

        # TMDB details cache — stores the result of GET /3/{movie|tv}/{id}
        # (title, original_title, year, alternative_titles) so the optional
        # ID-verification and AKA-hydration features don't re-hit TMDB for the
        # same id. `verified` records whether the id actually resolved (a
        # negative row means "TMDB has no such id" — surfaced as a mismatch).
        # Expiration is enforced in TMDBClient, not SQL, like tmdb_id_cache.
        tmdb_details_cache = TableDefinition(
            name="tmdb_details_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("tmdb_id", "INTEGER", nullable=False),
                ColumnDefinition("media_type", "TEXT", nullable=False),
                ColumnDefinition("title", "TEXT"),
                ColumnDefinition("original_title", "TEXT"),
                ColumnDefinition("year", "INTEGER"),
                ColumnDefinition("alternative_titles", "TEXT"),
                ColumnDefinition("verified", "BOOLEAN"),
                ColumnDefinition(
                    "cached_at", "TEXT", nullable=False, default="CURRENT_TIMESTAMP"
                ),
            ],
            constraints=[
                "UNIQUE (tmdb_id, media_type)",
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS tmdb_details_cache_lookup_idx ON tmdb_details_cache (tmdb_id, media_type)",
            ],
        )
        self._add_table(tmdb_details_cache)

        # Caches the selected image URLs from TMDB GET /3/{movie|tv}/{id}/images
        # (logo / background). Mandatory: asset_renamerr may run on a schedule,
        # and re-querying images for every media item each run would burn TMDB's
        # rate budget. Expiration enforced in TMDBClient, like the other caches.
        tmdb_images_cache = TableDefinition(
            name="tmdb_images_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("tmdb_id", "INTEGER", nullable=False),
                ColumnDefinition("media_type", "TEXT", nullable=False),
                # JSON {"logo": url|null, "background": url|null}
                ColumnDefinition("images", "TEXT"),
                ColumnDefinition(
                    "cached_at", "TEXT", nullable=False, default="CURRENT_TIMESTAMP"
                ),
            ],
            constraints=[
                "UNIQUE (tmdb_id, media_type)",
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS tmdb_images_cache_lookup_idx ON tmdb_images_cache (tmdb_id, media_type)",
            ],
        )
        self._add_table(tmdb_images_cache)

        # fanart.tv logo/background URL cache. Keyed by the id fanart is queried
        # with (tmdb for movies, tvdb for TV) + media_type + season. `season`
        # defaults to -1 for movies/show-level rows (NULLs would be distinct in
        # a UNIQUE, breaking upserts); a real season number is used for
        # season-specific backgrounds. Expiration enforced in FanartClient.
        fanart_images_cache = TableDefinition(
            name="fanart_images_cache",
            columns=[
                ColumnDefinition("id", "INTEGER", primary_key=True, nullable=False),
                ColumnDefinition("lookup_id", "TEXT", nullable=False),
                ColumnDefinition("media_type", "TEXT", nullable=False),
                ColumnDefinition("season", "INTEGER", nullable=False, default="-1"),
                # JSON {"logo": url|null, "background": url|null}
                ColumnDefinition("images", "TEXT"),
                ColumnDefinition(
                    "cached_at", "TEXT", nullable=False, default="CURRENT_TIMESTAMP"
                ),
            ],
            constraints=[
                "UNIQUE (lookup_id, media_type, season)",
            ],
            indexes=[
                "CREATE INDEX IF NOT EXISTS fanart_images_cache_lookup_idx ON fanart_images_cache (lookup_id, media_type, season)",
            ],
        )
        self._add_table(fanart_images_cache)

        # Tracks which one-shot data migrations have been applied.
        # See _run_rename_migrations for usage.
        # Per-instance last-completed-sync timestamp. Unlike a cache table's
        # row updated_at (which only moves when a row changes), this is written
        # once when a sync run finishes, so the "Synced N ago" signal reflects
        # the sync — not incidental row churn.
        sync_state = TableDefinition(
            name="sync_state",
            columns=[
                ColumnDefinition("scope", "TEXT", nullable=False),
                ColumnDefinition("instance_name", "TEXT", nullable=False),
                ColumnDefinition("synced_at", "TEXT", default="CURRENT_TIMESTAMP"),
            ],
            constraints=["PRIMARY KEY (scope, instance_name)"],
        )
        self._add_table(sync_state)

        schema_migrations = TableDefinition(
            name="schema_migrations",
            columns=[
                ColumnDefinition("name", "TEXT", primary_key=True, nullable=False),
                ColumnDefinition("applied_at", "TEXT", default="CURRENT_TIMESTAMP"),
            ],
        )
        self._add_table(schema_migrations)

        # Tables owned by self-registering extensions (backend/extensions).
        # Imported here, not at module level: manifests may import
        # TableDefinition from this module while it is still initialising.
        from backend.extensions import extension_tables

        for extension_table in extension_tables():
            self._add_table(extension_table)

        # Calculate schema hash for change detection
        self._calculate_schema_hash()

    def _add_table(self, table: TableDefinition) -> None:
        """Add table definition to schema."""
        self.tables[table.name] = table

    def _calculate_schema_hash(self) -> str:
        """Calculate hash of current schema definition."""
        schema_data = {}
        for table_name, table in self.tables.items():
            schema_data[table_name] = {
                "columns": [
                    (
                        col.name,
                        col.type,
                        col.nullable,
                        col.primary_key,
                        col.foreign_key,
                        col.default,
                        col.unique,
                        col.check_constraint,
                    )
                    for col in table.columns
                ],
                "indexes": table.indexes,
                "constraints": table.constraints,
            }

        schema_json = json.dumps(schema_data, sort_keys=True)
        self._schema_hash = hashlib.sha256(schema_json.encode()).hexdigest()
        return self._schema_hash

    @classmethod
    def get_existing_tables(cls, conn: sqlite3.Connection) -> Set[str]:
        """Get list of existing tables in the database."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in cursor.fetchall()}

    @classmethod
    def get_existing_indexes(cls, conn: sqlite3.Connection) -> Set[str]:
        """Get list of existing indexes in the database."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IS NOT NULL AND name NOT LIKE 'sqlite_%'"
        )
        return {row[0] for row in cursor.fetchall()}

    def get_table_columns(
        self, conn: sqlite3.Connection, table_name: str
    ) -> Dict[str, Dict]:
        """Get current column structure for a specific table."""
        cursor = conn.cursor()
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = {}
            for row in cursor.fetchall():
                columns[row[1]] = {  # row[1] is column name
                    "cid": row[0],
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "default_value": row[4],
                    "pk": bool(row[5]),
                }
            return columns
        except sqlite3.Error as e:
            logger.error(f"Failed to get columns for table {table_name}: {e}")
            return {}

    def add_missing_columns(self, conn: sqlite3.Connection) -> List[str]:
        """Add columns that exist in schema but not in database."""
        changes = []
        existing_tables = self.get_existing_tables(conn)
        cursor = conn.cursor()

        for table_name, table_def in self.tables.items():
            if table_name not in existing_tables:
                continue  # Will be handled by add_missing_tables

            current_columns = self.get_table_columns(conn, table_name)

            for column_def in table_def.columns:
                if column_def.name not in current_columns:
                    # Add missing column. Use the ADD COLUMN-safe clause (no
                    # UNIQUE / PRIMARY KEY / non-constant DEFAULT, which SQLite
                    # rejects on ALTER) and recreate uniqueness as an index.
                    alter_sql = (
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column_def.to_add_column_sql()}"
                    )
                    try:
                        cursor.execute(alter_sql)
                        if column_def.unique:
                            cursor.execute(
                                f"CREATE UNIQUE INDEX IF NOT EXISTS "
                                f"{table_name}_{column_def.name}_uq "
                                f"ON {table_name} ({column_def.name})"
                            )
                        changes.append(
                            f"Added column {column_def.name} to {table_name}"
                        )
                        logger.info(
                            f"Added column {column_def.name} to table {table_name}"
                        )
                    except sqlite3.Error as e:
                        logger.warning(
                            f"[schema] Could not add column {column_def.name} to "
                            f"{table_name} via ALTER ({e}); a one-time table "
                            f"rebuild may be required for this column."
                        )

        return changes

    def _run_rename_migrations(self, conn: sqlite3.Connection) -> None:
        """One-shot data migrations for tables that were renamed or removed.

        Idempotent — safe to call on every startup. Migrations that aren't
        naturally idempotent (e.g. unconditional UPDATEs) gate on the
        `schema_migrations` table so they only run once.
        """
        cursor = conn.cursor()
        existing = self.get_existing_tables(conn)

        # Drop the legacy deletion-queue tables. The feature they powered was
        # removed; the queue never auto-drained (only a webhook fired it), so
        # any rows still in either table are effectively abandoned.
        for legacy in ("orphaned_posters", "pending_deletions"):
            if legacy in existing:
                try:
                    cursor.execute(f"DROP TABLE {legacy}")
                    logger.info(f"Dropped legacy {legacy} table")
                except sqlite3.Error as e:
                    logger.error(f"Failed to drop {legacy}: {e}")

        # When `has_content` was added to media_cache, the ALTER TABLE used
        # DEFAULT 1, which back-filled every existing row with True regardless
        # of whether the *arr instance actually had a file. That made the
        # `has_content=0` filter in unmatched_assets useless until the next
        # full sync re-stamped every row. Null those rows out so the filter
        # falls through to the *arr `status` check until a fresh sync runs.
        self._apply_once(
            conn,
            "20260522_null_has_content_default_rows",
            "UPDATE media_cache SET has_content = NULL WHERE has_content = 1",
            requires_table="media_cache",
        )

        # Before season_number_regex was tightened to require plural
        # 'Specials', singular 'Special' in a movie title (e.g. "X-Men
        # First Class 35mm Special", "Mariah Carey's Magical Christmas
        # Special") got matched as a season-0 marker. Each affected
        # poster file landed in poster_cache with asset_type='show',
        # season_number=0, and a truncated title — so the matcher could
        # never link it to the corresponding Radarr row. The fix to the
        # regex prevents new rows from being mis-stored, but existing
        # rows are keyed under the wrong (asset_type, season_number)
        # tuple and won't be overwritten by poster_renamerr's
        # delete-then-insert path on the next scan. Purge them here so
        # the next scan can insert clean rows without orphan ghosts
        # lingering. The heuristic distinguishes legitimate season-0
        # rows (whose files end in 'Specials.<ext>' or use ' - Specials '
        # / '_ Specials' separators) from movie casualties, verified
        # against real data: catches the 71 known-bad rows, touches
        # none of the legitimate ~1,700 Specials season rows.
        self._apply_once(
            conn,
            "20260522_purge_orphan_specials_show_rows",
            """
            DELETE FROM poster_cache
            WHERE asset_type = 'show'
              AND season_number = 0
              AND file LIKE '%Special%'
              AND file NOT LIKE '%Specials.%'
              AND file NOT LIKE '%- Specials %'
              AND file NOT LIKE '%_ Specials%'
            """,
            requires_table="poster_cache",
        )

        # Same bug class as the Specials purge above, for the "Season <n>"
        # variant: a bare "Season N" inside a *movie title* ("Open Season 2",
        # "Open Season 3") was eaten as a TV season marker by the old
        # delimiter-optional season_number_regex — landing those posters in
        # poster_cache with a non-null season_number and a truncated title.
        # The regex now requires a " - "/"_" delimiter, so new scans store them
        # correctly, but existing mis-stored rows are keyed under the wrong
        # (asset_type, season_number) tuple and linger. A real season poster
        # always delimits its tag (" - Season N", "_SeasonNN"), so any
        # season-tagged row whose filename lacks that delimiter is a movie
        # casualty — purge it so the next scan re-inserts a clean movie row.
        self._apply_once(
            conn,
            "20260530_purge_orphan_bare_season_show_rows",
            """
            DELETE FROM poster_cache
            WHERE season_number IS NOT NULL
              AND file NOT LIKE '%- Season%'
              AND file NOT LIKE '%_Season%'
              AND file NOT LIKE '%/Season%'
              AND file NOT LIKE '%- Specials%'
              AND file NOT LIKE '%_Specials%'
              AND file NOT LIKE '%/Specials%'
            """,
            requires_table="poster_cache",
        )

        # The first TMDB id-verification pass conflated a transient TMDB error
        # (rate limit / network / 5xx) with a genuine 404 — both negative-cached
        # the id and flagged the media row as "not found on TMDB", even for ids
        # that exist (e.g. Married with Children, tmdb tv/4239). The client now
        # distinguishes the two, but the bad negatives + bogus flags linger.
        # Purge the negative details-cache rows so they re-verify cleanly...
        self._apply_once(
            conn,
            "20260530_purge_negative_tmdb_details_cache",
            "DELETE FROM tmdb_details_cache WHERE verified = 0",
            requires_table="tmdb_details_cache",
        )
        # ...and clear the bogus review flags so those rows drop out of Needs
        # Review (the next poster_renamerr run re-stamps the real match_status).
        self._apply_once(
            conn,
            "20260530_clear_bogus_tmdb_not_found_flags",
            "UPDATE media_cache SET match_status = NULL, match_reason = NULL "
            "WHERE match_reason LIKE '%not found on TMDB%'",
            requires_table="media_cache",
        )

    def _apply_once(
        self,
        conn: sqlite3.Connection,
        name: str,
        sql: str,
        requires_table: Optional[str] = None,
    ) -> None:
        """Run a one-shot SQL migration if it hasn't been recorded yet.

        Use for data migrations that aren't naturally idempotent — typically
        UPDATEs or DELETEs that would corrupt state on a second run.
        Schema-shape changes (ADD COLUMN / CREATE TABLE) don't need this
        helper because `add_missing_columns` / `add_missing_tables` already
        skip already-applied changes.

        To add a new migration:

          1. Inside `_run_rename_migrations`, add a call:

             self._apply_once(
                 conn,
                 "YYYYMMDD_short_human_label",
                 "UPDATE foo SET bar = NULL WHERE baz = 1",
                 requires_table="foo",  # skip if the table isn't there yet
             )

          2. Pick a unique `name` — the value goes into `schema_migrations`
             as the de-duplication key. Convention: ISO date + lowercase
             snake_case label describing the intent.

          3. The SQL runs inside the existing `with conn:` block from
             `sync_schema`, so it commits atomically with the rest of the
             schema-sync pass.

          4. If the migration alters a table that needs to exist first,
             pass `requires_table=` so the migration is a no-op on fresh
             installs where the table will be created later in the same
             sync (and so won't have the bad data anyway).

        Each `name` is gated by the `schema_migrations` table — once
        recorded, the migration is permanently skipped on subsequent
        startups even if the underlying data drifts back into the
        triggering shape.
        """
        cursor = conn.cursor()
        if "schema_migrations" not in self.get_existing_tables(conn):
            return  # Migration table not yet created; nothing to gate on.
        if requires_table and requires_table not in self.get_existing_tables(conn):
            return
        cursor.execute("SELECT 1 FROM schema_migrations WHERE name = ?", (name,))
        if cursor.fetchone() is not None:
            return
        try:
            cursor.execute(sql)
            cursor.execute(
                "INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (name,)
            )
            logger.info(f"Applied data migration: {name}")
        except sqlite3.Error as e:
            logger.error(f"Failed to apply data migration {name}: {e}")

    def add_missing_tables(self, conn: sqlite3.Connection) -> List[str]:
        """Create tables that exist in schema but not in database."""
        changes = []
        existing_tables = self.get_existing_tables(conn)
        cursor = conn.cursor()

        for table_name, table_def in self.tables.items():
            if table_name not in existing_tables:
                # Create missing table
                create_sql = table_def.to_create_sql()
                try:
                    cursor.execute(create_sql)
                    changes.append(f"Created table {table_name}")
                    logger.info(f"Created table {table_name}")

                    # Create indexes for new table
                    for index_sql in table_def.indexes:
                        try:
                            cursor.execute(index_sql)
                            changes.append(f"Created index for {table_name}")
                        except sqlite3.Error as e:
                            logger.warning(
                                f"Failed to create index for {table_name}: {e}"
                            )

                except sqlite3.Error as e:
                    logger.error(f"Failed to create table {table_name}: {e}")

        return changes

    def add_missing_indexes(self, conn: sqlite3.Connection) -> List[str]:
        """Create indexes that exist in schema but not in database."""
        changes = []
        existing_indexes = self.get_existing_indexes(conn)
        cursor = conn.cursor()

        for table_name, table_def in self.tables.items():
            for index_sql in table_def.indexes:
                # Extract index name from SQL
                try:
                    index_name = index_sql.split()[
                        5
                    ]  # "CREATE INDEX IF NOT EXISTS index_name ..."
                    if index_name not in existing_indexes:
                        cursor.execute(index_sql)
                        changes.append(f"Created index: {index_name}")
                        logger.info(f"Created index: {index_name}")
                except (IndexError, sqlite3.Error) as e:
                    logger.warning(
                        f"Failed to create index from SQL: {index_sql} - {e}"
                    )

        return changes

    def sync_schema(
        self, conn: sqlite3.Connection, add_missing_columns: bool = True
    ) -> Dict[str, List[str]]:
        """
        Synchronize database schema with the defined tables and indexes.
        Enhanced version with automatic column addition support.

        Args:
            conn: Database connection
            add_missing_columns: Whether to automatically add missing columns

        Returns:
            Dictionary of changes made by category
        """
        logger.debug("Synchronizing database schema...")

        changes = {
            "tables_added": [],
            "columns_added": [],
            "indexes_added": [],
            "orphaned_tables": [],
            "orphaned_indexes": [],
        }

        existing_tables = self.get_existing_tables(conn)
        existing_indexes = self.get_existing_indexes(conn)

        with conn:
            # Add missing tables
            changes["tables_added"] = self.add_missing_tables(conn)

            # Add missing columns (if enabled) BEFORE the one-shot migrations:
            # a column-targeted migration UPDATE (e.g. the has_content backfill)
            # would otherwise raise "no such column" on an upgrade that predates
            # the column, fail to record success, and re-attempt every startup.
            if add_missing_columns:
                changes["columns_added"] = self.add_missing_columns(conn)

            # One-shot rename / data migrations (legacy table -> new table, and
            # column-targeted backfills) — now run against the fully-formed
            # schema.
            self._run_rename_migrations(conn)

            # Add missing indexes
            changes["indexes_added"] = self.add_missing_indexes(conn)

            # Log orphaned tables for manual review (don't auto-drop)
            orphaned_tables = (
                existing_tables
                - set(self.tables.keys())
                - {"sqlite_master", "sqlite_sequence", "sqlite_stat1"}
            )
            if orphaned_tables:
                changes["orphaned_tables"] = list(orphaned_tables)
                logger.debug(
                    f"Found orphaned tables (manual cleanup needed): {orphaned_tables}"
                )

            # Log orphaned indexes for manual review (don't auto-drop)
            schema_indexes = set()
            for table_def in self.tables.values():
                for index_sql in table_def.indexes:
                    try:
                        index_name = index_sql.split()[5]  # Extract index name
                        schema_indexes.add(index_name)
                    except IndexError:
                        pass

            orphaned_indexes = existing_indexes - schema_indexes
            if orphaned_indexes:
                changes["orphaned_indexes"] = list(orphaned_indexes)
                logger.debug(
                    f"Found orphaned indexes (manual cleanup needed): {orphaned_indexes}"
                )

        # Log summary
        total_changes = (
            len(changes["tables_added"])
            + len(changes["columns_added"])
            + len(changes["indexes_added"])
        )
        if total_changes > 0:
            logger.info(
                f"Schema synchronization complete: {total_changes} changes made"
            )
        else:
            logger.debug("Schema already up to date")

        return changes

    @classmethod
    def init_database(
        cls, conn: sqlite3.Connection, add_missing_columns: bool = True
    ) -> Dict[str, List[str]]:
        """
        Initialize database with proper settings and schema.

        Args:
            conn: Database connection
            add_missing_columns: Whether to automatically add missing columns

        Returns:
            Dictionary of changes made during synchronization
        """
        # Set database pragmas for better performance and reliability
        with conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB
            conn.execute("PRAGMA foreign_keys=ON")

        # Create schema manager and sync
        schema_manager = cls()
        return schema_manager.sync_schema(conn, add_missing_columns=add_missing_columns)

    @classmethod
    def manual_cleanup_tables(
        cls, conn: sqlite3.Connection, table_names: List[str]
    ) -> None:
        """
        Manually drop specified tables - use with caution!

        Args:
            conn: Database connection
            table_names: List of table names to drop
        """
        logger.warning(f"Manual table cleanup requested for: {table_names}")

        with conn:
            for table_name in table_names:
                logger.warning(f"Dropping table: {table_name}")
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        logger.warning("Manual table cleanup completed")

    @classmethod
    def manual_cleanup_indexes(
        cls, conn: sqlite3.Connection, index_names: List[str]
    ) -> None:
        """
        Manually drop specified indexes - use with caution!

        Args:
            conn: Database connection
            index_names: List of index names to drop
        """
        logger.warning(f"Manual index cleanup requested for: {index_names}")

        with conn:
            for index_name in index_names:
                logger.warning(f"Dropping index: {index_name}")
                conn.execute(f"DROP INDEX IF EXISTS {index_name}")

        logger.warning("Manual index cleanup completed")

    def get_schema_status(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        """Get comprehensive schema status and differences."""
        existing_tables = self.get_existing_tables(conn)
        existing_indexes = self.get_existing_indexes(conn)

        # Get schema indexes
        schema_indexes = set()
        for table_def in self.tables.values():
            for index_sql in table_def.indexes:
                try:
                    index_name = index_sql.split()[5]
                    schema_indexes.add(index_name)
                except IndexError:
                    pass

        # Check for missing columns
        missing_columns = {}
        for table_name, table_def in self.tables.items():
            if table_name in existing_tables:
                current_columns = self.get_table_columns(conn, table_name)
                missing = [
                    col.name
                    for col in table_def.columns
                    if col.name not in current_columns
                ]
                if missing:
                    missing_columns[table_name] = missing

        return {
            "schema_hash": self._schema_hash,
            "tables": {
                "defined": set(self.tables.keys()),
                "existing": existing_tables,
                "missing": set(self.tables.keys()) - existing_tables,
                "orphaned": existing_tables
                - set(self.tables.keys())
                - {"sqlite_master", "sqlite_sequence", "sqlite_stat1"},
            },
            "indexes": {
                "defined": schema_indexes,
                "existing": existing_indexes,
                "missing": schema_indexes - existing_indexes,
                "orphaned": existing_indexes - schema_indexes,
            },
            "columns": {"missing_by_table": missing_columns},
        }


# Convenience function for easy usage
def ensure_schema_current(
    db_path: str, add_missing_columns: bool = True
) -> Dict[str, List[str]]:
    """
    Ensure database schema is current with definition.

    Args:
        db_path: Path to SQLite database
        add_missing_columns: Whether to automatically add missing columns

    Returns:
        Dictionary of changes made
    """
    with sqlite3.connect(db_path) as conn:
        return SchemaManager.init_database(
            conn, add_missing_columns=add_missing_columns
        )
