# util/database/db_base.py

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from backend.util.logger import Logger


class DatabaseBase:
    """Base class for all database operations with proper resource management."""

    def __init__(self, logger: Logger, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_db_directory()
        self.lock = threading.Lock()
        self.logger = logger

        try:
            self.init_schema(self.db_path)
        except Exception as e:
            # Don't crash startup if schema init races; just log
            self.logger.error(f"Schema initialization error: {e}")

    def _ensure_db_directory(self) -> None:
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.
        Ensures proper connection cleanup and thread safety.
        """
        conn = None
        try:
            with self.lock:
                # timeout + busy_timeout: the per-accessor self.lock only
                # serializes writers sharing THIS instance; separate ChubDB
                # instances (per request/worker/thread) hold distinct locks, so
                # writer-vs-writer contention falls to SQLite. Without a busy
                # timeout that surfaces immediately as "database is locked".
                # Wait up to 30s for the write lock instead (WAL keeps readers
                # non-blocking, so this only affects concurrent writers).
                conn = sqlite3.connect(
                    self.db_path, check_same_thread=False, timeout=30
                )
                conn.execute("PRAGMA busy_timeout=30000")
                # journal_mode=WAL is persistent (lives in the DB header), but
                # synchronous is per-connection and resets to the compile-time
                # default (FULL) on every new connection. schema.py declares
                # NORMAL at init; without re-asserting it here every runtime
                # commit fsyncs (FULL), which dominates per-row write loops on
                # spinning/FUSE arrays (~25-37ms/row vs sub-ms). NORMAL+WAL
                # cannot corrupt and only risks the last txn on power loss —
                # acceptable for these regenerable caches.
                conn.execute("PRAGMA synchronous=NORMAL")
                # Also per-connection. SQLite's 2MB default thrashes on a
                # 100MB+ poster_cache; 20MB matches what Sonarr ships.
                conn.execute("PRAGMA cache_size=-20000")
                conn.row_factory = self._dict_factory
                yield conn
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _dict_factory(self, cursor: Any, row: Any) -> Dict[str, Any]:
        """Return rows as dictionaries."""
        return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

    def open_read_connection(self) -> sqlite3.Connection:
        """Open a reusable READ-ONLY connection for tight read loops (e.g. the
        asset resolve loop, which fires several poster_cache lookups per item).

        Pass the returned connection to ``execute_query(conn=...)`` to skip the
        per-query connect/PRAGMA/close churn — the caller pays one connect for
        the whole loop. **The caller owns it and must ``close()`` it.**

        Unlike :meth:`get_connection` this does NOT hold ``self.lock`` for its
        lifetime: it issues only SELECTs and WAL keeps readers non-blocking, so
        there's no writer to serialize against. ``query_only=ON`` enforces the
        read-only contract (any write raises), so it can never corrupt data or
        hold a write transaction open.
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA cache_size=-20000")
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = self._dict_factory
        return conn

    def execute_query(
        self,
        sql: str,
        params: Tuple[Any, ...] = (),
        fetch_all: bool = False,
        fetch_one: bool = False,
        last_row_id: bool = False,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any], int, None]:
        """
        Execute a query with proper connection handling.

        Args:
            sql: SQL query to execute
            params: Parameters for the query
            fetch_all: Return all results
            fetch_one: Return one result
            conn: Reuse this caller-owned connection instead of opening one
                (see open_read_connection). Read-only — only the fetch paths are
                valid; writes raise (the connection is query_only).

        Returns:
            Query results or None
        """
        if conn is not None:
            cursor = conn.execute(sql, params)
            if fetch_all:
                return cursor.fetchall()
            if fetch_one:
                return cursor.fetchone()
            return cursor.rowcount
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            if fetch_all:
                return cursor.fetchall()
            if last_row_id:
                conn.commit()
                return cursor.lastrowid
            elif fetch_one:
                return cursor.fetchone()
            else:
                conn.commit()
                return cursor.rowcount

    def execute_transaction(
        self, operations: List[Tuple[str, Tuple[Any, ...]]]
    ) -> None:
        """
        Execute multiple operations in a single transaction.

        Args:
            operations: List of (sql, params) tuples
        """
        with self.get_connection() as conn:
            for sql, params in operations:
                conn.execute(sql, params)
            conn.commit()

    @staticmethod
    def init_schema(db_path: str) -> None:
        """Initialize database schema - called by ChubDB."""
        from .schema import SchemaManager

        conn = sqlite3.connect(db_path)
        try:
            SchemaManager.init_database(conn)
        finally:
            conn.close()
