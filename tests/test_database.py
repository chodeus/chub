"""Smoke tests for database initialization and schema."""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database.schema import SchemaManager


class TestSchemaManager:
    """Test database schema creation."""

    def test_schema_init_creates_tables(self):
        """init_database should create all expected tables."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            SchemaManager.init_database(conn)

            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {row[0] for row in cursor.fetchall()}

            # Core tables that should exist
            expected_tables = {
                "media_cache",
                "poster_cache",
                "jobs",
            }

            for table in expected_tables:
                assert table in tables, f"Expected table '{table}' not found. Tables: {tables}"

            conn.close()
        finally:
            os.unlink(db_path)

    def test_schema_idempotent(self):
        """Running init_database twice should not error."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            SchemaManager.init_database(conn)
            # Run again - should be safe
            SchemaManager.init_database(conn)
            conn.close()
        finally:
            os.unlink(db_path)

    def test_wal_mode_enabled(self):
        """Database should use WAL journal mode for performance."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            SchemaManager.init_database(conn)

            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode == "wal", f"Expected WAL mode, got {mode}"

            conn.close()
        finally:
            os.unlink(db_path)
