# util/database/__init__.py

import os
import threading
from typing import List, Optional

from backend.util.helper import get_config_dir
from backend.util.logger import Logger

from .border_state import BorderState
from .collection_cache import CollectionCache
from .db_base import DatabaseBase
from .holiday import HolidayStatus
from .media_asset_matches import MediaAssetMatches
from .media_cache import MediaCache
from .plex_cache import PlexCache
from .poster_cache import PosterCache
from .run_state import RunState
from .schema import SchemaManager
from .stats import Stats
from .sync_state import SyncState
from .tmdb_id_cache import TmdbIdCache
from .tmdb_details_cache import TmdbDetailsCache
from .tmdb_images_cache import TmdbImagesCache
from .fanart_images_cache import FanartImagesCache
from .upgradinatorr_progress import UpgradinatorrProgress
from .webhook_cache import WebhookCache
from .worker import DBWorker


class ChubDB:
    """
    Main database context manager providing clean access to all database operations.

    Usage:
        with ChubDB(logger) as db:
            results = db.run_state.get_all()

    Features:
    - Lazy initialization of database interfaces
    - Automatic worker cleanup on exit
    - Schema initialization on first use
    - Quiet mode for frequently polled operations
    """

    def __init__(
        self, logger: Logger, db_path: Optional[str] = None, quiet: bool = False
    ):
        """
        Initialize database context manager.

        Args:
            logger: Logger instance for database operations
            db_path: Optional custom database path (defaults to config/chub.db)
            quiet: Suppress debug logging for frequently polled operations
        """
        self.logger = logger
        self.quiet = quiet
        self._initialized = False
        self._schema_initialized = False

        # Determine database path
        if db_path:
            self.db_path = db_path
        else:
            config_dir = get_config_dir()
            self.db_path = os.path.join(config_dir, "chub.db")

        # Database interfaces (lazy-loaded). The lock guards the check-then-set
        # in _get_interface: a single ChubDB is shared between async API
        # handlers and worker threads, and constructing an interface re-runs
        # init_schema (blocking I/O that releases the GIL), so two threads could
        # otherwise both miss the cache and double-construct.
        self._interfaces = {}
        self._interfaces_lock = threading.Lock()

        # Track created workers for cleanup
        self.created_workers: List[DBWorker] = []

    def __enter__(self) -> "ChubDB":
        """Context manager entry - marks database as ready for use."""
        self._initialized = True
        if not self.quiet:
            self.logger.get_adapter("DATABASE").debug("Database context initialized")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Context manager exit - ensures proper cleanup of resources."""
        if not self.quiet:
            self.logger.get_adapter("DATABASE").debug("Cleaning up database context")

        # Clean up workers
        self._cleanup_workers()

        # Clear interfaces
        self._interfaces.clear()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure database context is properly initialized."""
        if not self._initialized:
            raise RuntimeError("ChubDB must be used within a context manager")

    def _ensure_schema_initialized(self) -> None:
        """Lazy initialization of database schema."""
        if not self._schema_initialized:
            try:
                DatabaseBase(logger=self.logger, db_path=self.db_path).init_schema(
                    self.db_path
                )
                self._schema_initialized = True
                if not self.quiet:
                    self.logger.get_adapter("DATABASE").debug(
                        "Database schema initialized"
                    )
            except Exception as e:
                self.logger.get_adapter("DATABASE").error(
                    f"Failed to initialize database schema: {e}"
                )
                raise

    def _get_interface(self, interface_name: str, interface_class):
        """
        Generic interface getter with lazy loading.

        Args:
            interface_name: Name of the interface for caching
            interface_class: Class to instantiate for the interface

        Returns:
            Database interface instance
        """
        self._ensure_initialized()
        self._ensure_schema_initialized()

        if interface_name not in self._interfaces:
            with self._interfaces_lock:
                # Re-check inside the lock (another thread may have built it).
                if interface_name not in self._interfaces:
                    self._interfaces[interface_name] = interface_class(
                        logger=self.logger, db_path=self.db_path
                    )

        return self._interfaces[interface_name]

    def extension_interface(self, interface_name: str, interface_class):
        """Public accessor for extension-owned database interfaces.

        Extensions (backend/extensions) can't add properties to ChubDB, so
        they reach their interfaces through this instead — same lazy
        caching as the core properties below.
        """
        return self._get_interface(interface_name, interface_class)

    def _cleanup_workers(self) -> None:
        """Clean up all created workers with proper error handling."""
        for worker in self.created_workers:
            try:
                if hasattr(worker, "running") and worker.running:
                    worker.close()
                    if not self.quiet:
                        self.logger.get_adapter("DATABASE").debug(
                            f"Closed worker: {getattr(worker, 'worker_name', 'UNKNOWN')}"
                        )
            except Exception as e:
                self.logger.get_adapter("DATABASE").warning(
                    f"Error closing worker: {e}"
                )

        self.created_workers.clear()

    # Database interface properties with lazy loading
    @property
    def media(self) -> MediaCache:
        """Access to media cache operations."""
        return self._get_interface("media", MediaCache)

    @property
    def plex(self) -> PlexCache:
        """Access to Plex cache operations."""
        return self._get_interface("plex", PlexCache)

    @property
    def collection(self) -> CollectionCache:
        """Access to collection cache operations."""
        return self._get_interface("collection", CollectionCache)

    @property
    def poster(self) -> PosterCache:
        """Access to poster cache operations."""
        return self._get_interface("poster", PosterCache)

    @property
    def border(self) -> BorderState:
        """Access to border-replacerr skip-gate state."""
        return self._get_interface("border", BorderState)

    @property
    def media_asset_matches(self) -> MediaAssetMatches:
        """Access to per-(media, image_type) asset match provenance."""
        return self._get_interface("media_asset_matches", MediaAssetMatches)

    @property
    def run_state(self) -> RunState:
        """Access to run state operations."""
        return self._get_interface("run_state", RunState)

    @property
    def stats(self) -> Stats:
        """Access to statistics operations."""
        return self._get_interface("stats", Stats)

    @property
    def sync_state(self) -> SyncState:
        """Access to per-instance last-completed-sync timestamps."""
        return self._get_interface("sync_state", SyncState)

    @property
    def holiday(self) -> HolidayStatus:
        """Access to holiday status operations."""
        return self._get_interface("holiday", HolidayStatus)

    @property
    def webhook_cache(self) -> WebhookCache:
        """Access to persistent webhook dedup cache."""
        return self._get_interface("webhook_cache", WebhookCache)

    @property
    def upgradinatorr_progress(self) -> UpgradinatorrProgress:
        """Access to Upgradinatorr per-child progress tracking."""
        return self._get_interface("upgradinatorr_progress", UpgradinatorrProgress)

    @property
    def tmdb_id_cache(self) -> TmdbIdCache:
        """Access to TMDB external-ID lookup cache."""
        return self._get_interface("tmdb_id_cache", TmdbIdCache)

    @property
    def tmdb_details_cache(self) -> TmdbDetailsCache:
        """Access to TMDB details cache (id verification / AKA hydration)."""
        return self._get_interface("tmdb_details_cache", TmdbDetailsCache)

    @property
    def tmdb_images_cache(self) -> TmdbImagesCache:
        """Access to TMDB images cache (logo / background URLs)."""
        return self._get_interface("tmdb_images_cache", TmdbImagesCache)

    @property
    def fanart_images_cache(self) -> FanartImagesCache:
        """Access to fanart.tv images cache (logo / background URLs)."""
        return self._get_interface("fanart_images_cache", FanartImagesCache)

    @property
    def worker(self) -> DBWorker:
        """Access to default worker operations."""
        return self._get_interface(
            "worker", lambda **kwargs: DBWorker(worker_name="DEFAULT", **kwargs)
        )

    def create_worker(
        self,
        logger: Optional[Logger] = None,
        num_workers: int = 1,
        worker_name: str = "UNNAMED",
        job_type_filter: Optional[str] = None,
    ) -> DBWorker:
        """
        Create a new database worker for background operations.

        Args:
            logger: Optional logger (defaults to database logger)
            num_workers: Number of worker threads
            worker_name: Name for the worker (for logging/debugging)
            job_type_filter: Optional filter for specific job types

        Returns:
            Configured DBWorker instance

        Raises:
            RuntimeError: If called outside context manager
        """
        self._ensure_initialized()

        worker_logger = logger or self.logger

        if not self.quiet:
            self.logger.get_adapter("DATABASE").debug(
                f"Creating worker: '{worker_name}'"
            )

        try:
            worker = DBWorker(
                db_path=self.db_path,
                logger=worker_logger,
                num_workers=num_workers,
                worker_name=worker_name,
                job_type_filter=job_type_filter,
            )

            # Track for cleanup
            self.created_workers.append(worker)
            return worker

        except Exception as e:
            self.logger.get_adapter("DATABASE").error(
                f"Failed to create worker '{worker_name}': {e}"
            )
            raise

    def rename_instance(self, old_name: str, new_name: str, service: str) -> int:
        """Migrate cached rows from one instance name to another after a config
        rename, so the rename is invisible to stats/freshness/progress.

        Type-scoped: tables that record the service (media_cache.source,
        system_health_snapshots.service, sync_state.scope) only have their
        rows for ``service`` touched, and single-service tables are gated by
        service — a same-named instance of another service is left untouched.
        Returns the number of rows migrated.
        """
        self._ensure_initialized()
        if not old_name or not new_name or old_name == new_name:
            return 0

        # (table, type_column) — type_column None means single-service; which
        # services those apply to is in single_service below.
        tables = [
            ("media_cache", "source"),
            ("system_health_snapshots", "service"),
            ("sync_state", "scope"),
            ("plex_media_cache", None),
            ("collections_cache", None),
            ("upgradinatorr_progress", None),
        ]
        single_service = {
            "plex_media_cache": {"plex"},
            "collections_cache": {"plex"},
            "upgradinatorr_progress": {"radarr", "sonarr"},
        }

        total = 0
        for table, type_col in tables:
            allowed = single_service.get(table)
            if allowed is not None and service not in allowed:
                continue
            if type_col:
                sql = (
                    f"UPDATE {table} SET instance_name = ? "  # noqa: S608 (table is a fixed literal)
                    f"WHERE instance_name = ? AND {type_col} = ?"
                )
                params: tuple = (new_name, old_name, service)
            else:
                sql = f"UPDATE {table} SET instance_name = ? WHERE instance_name = ?"  # noqa: S608
                params = (new_name, old_name)
            total += self.media.execute_query(sql, params) or 0

        if not self.quiet:
            self.logger.get_adapter("DATABASE").info(
                f"rename_instance: migrated {total} cached row(s) from "
                f"'{old_name}' to '{new_name}' ({service})"
            )
        return total

    def close(self) -> None:
        """
        Manually close the database context.
        Useful for cleanup without exiting context manager.
        """
        if self._initialized:
            self._cleanup_workers()
            self._interfaces.clear()


# Utility function for simple database operations
def with_database(logger: Logger, quiet: bool = False):
    """
    Decorator/context helper for simple database operations.

    Args:
        logger: Logger instance
        quiet: Suppress debug logging

    Returns:
        ChubDB context manager

    Usage:
        # As context manager
        with with_database(logger) as db:
            results = db.run_state.get_all()

        # As decorator (for future use)
        @with_database(logger)
        def my_db_operation(db):
            return db.stats.get_summary()
    """
    return ChubDB(logger=logger, quiet=quiet)


__all__ = [
    "DatabaseBase",
    "SchemaManager",
    "PlexCache",
    "CollectionCache",
    "PosterCache",
    "RunState",
    "Stats",
    "SyncState",
    "ChubDB",
    "DBWorker",
    "HolidayStatus",
    "MediaCache",
    "MediaAssetMatches",
    "WebhookCache",
    "with_database",
]
