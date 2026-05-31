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
                "media_asset_matches",
                "tmdb_images_cache",
                "jobs",
            }

            for table in expected_tables:
                assert table in tables, f"Expected table '{table}' not found. Tables: {tables}"

            # poster_cache must carry the image_type column (defaults to poster)
            cursor.execute("PRAGMA table_info(poster_cache)")
            cols = {row[1] for row in cursor.fetchall()}
            assert "image_type" in cols

            conn.close()
        finally:
            os.unlink(db_path)

    def test_poster_cache_image_type_defaults_to_poster(self):
        """A row inserted without image_type back-fills to 'poster' (so legacy
        rows behave as posters)."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            SchemaManager.init_database(conn)
            conn.execute(
                "INSERT INTO poster_cache (title, file) VALUES ('X', '/x/X.png')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT image_type FROM poster_cache WHERE file='/x/X.png'"
            ).fetchone()
            assert row[0] == "poster"
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
