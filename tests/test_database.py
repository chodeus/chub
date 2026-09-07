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
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
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
                assert (
                    table in tables
                ), f"Expected table '{table}' not found. Tables: {tables}"

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


def _stub_sync(syncs):
    """init_database stand-in that records the call and leaves the file non-empty."""

    def _init(cls, conn, **_kw):
        """Record one sync and write a marker table."""
        syncs.append(1)
        conn.execute("CREATE TABLE IF NOT EXISTS marker (x INTEGER)")
        conn.commit()

    return classmethod(_init)


def test_init_schema_syncs_each_db_file_once(monkeypatch, tmp_path):
    """Every interface construction calls init_schema; only the first may sync."""
    from backend.util.database import db_base

    syncs = []
    monkeypatch.setattr(SchemaManager, "init_database", _stub_sync(syncs))

    db_path = str(tmp_path / "chub.db")
    db_base.DatabaseBase.init_schema(db_path)
    db_base.DatabaseBase.init_schema(db_path)
    assert len(syncs) == 1

    # A different file still syncs, and force re-runs an already-synced one.
    db_base.DatabaseBase.init_schema(str(tmp_path / "other.db"))
    db_base.DatabaseBase.init_schema(db_path, force=True)
    assert len(syncs) == 3


def test_init_schema_resyncs_a_recreated_empty_db(monkeypatch, tmp_path):
    """Inode reuse can hand a brand-new empty db an already-synced identity."""
    from backend.util.database import db_base

    syncs = []
    monkeypatch.setattr(SchemaManager, "init_database", _stub_sync(syncs))

    db_path = str(tmp_path / "chub.db")
    db_base.DatabaseBase.init_schema(db_path)
    assert len(syncs) == 1

    # Stand in for delete+recreate landing on the SAME inode: a 0-byte file
    # whose identity the registry already holds.
    os.unlink(db_path)
    open(db_path, "wb").close()
    identity, size = db_base._schema_file_state(db_path)
    db_base._SCHEMA_SYNCED.add(identity)
    assert size == 0

    db_base.DatabaseBase.init_schema(db_path)
    assert len(syncs) == 2, "an empty db at a reused identity must re-sync"


def test_collection_update_persists_file_hash_and_mtime():
    """collection_cache.update must accept file_hash/file_mtime (previously it
    didn't, so collection poster hashes were never stored → re-upload every run)."""
    import tempfile
    from backend.util.database import ChubDB

    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None

        def get_adapter(self, *a, **k):
            return self

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with ChubDB(_Log(), db_path=db_path) as db:
            db.collection.execute_query(
                "INSERT INTO collections_cache (title, library_name, instance_name) "
                "VALUES ('Good Burger Collection','Movies','plex1')"
            )
            db.collection.update(
                title="Good Burger Collection",
                year=None,
                library_name="Movies",
                instance_name="plex1",
                file_hash="abc123",
                file_mtime=1234.5,
            )
            row = db.collection.execute_query(
                "SELECT file_hash, file_mtime FROM collections_cache "
                "WHERE title='Good Burger Collection'",
                fetch_one=True,
            )
            assert row["file_hash"] == "abc123"
            assert float(row["file_mtime"]) == 1234.5
    finally:
        os.unlink(db_path)


def test_browse_image_type_filtering():
    """browse() defaults to posters; image_type='artwork' returns only the
    additional-artwork set (logo/squareart/background), never posters/banners;
    a specific image_type returns just that type."""
    import tempfile
    from backend.util.database import ChubDB

    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None

        def get_adapter(self, *a, **k):
            return self

    rows = [
        ("Alpha", "/p/Alpha.png", "poster"),
        ("Beta", "/p/Beta - Logo.png", "logo"),
        ("Gamma", "/p/Gamma - Background.png", "background"),
        ("Delta", "/p/Delta - SquareArt.png", "squareart"),
        ("Epsilon", "/p/Epsilon - Banner.png", "banner"),
    ]

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with ChubDB(_Log(), db_path=db_path) as db:
            for title, file, image_type in rows:
                db.poster.execute_query(
                    "INSERT INTO poster_cache (title, file, image_type) VALUES (?, ?, ?)",
                    (title, file, image_type),
                )

            # Default: posters only.
            default = db.poster.browse()
            assert {r["image_type"] for r in default["items"]} == {"poster"}

            # 'artwork' → the three processable artwork types, excluding
            # posters and (unprocessed) banners.
            artwork = db.poster.browse(image_type="artwork")
            assert {r["image_type"] for r in artwork["items"]} == {
                "logo",
                "squareart",
                "background",
            }
            assert artwork["total"] == 3

            # A specific type narrows to exactly that type.
            logos = db.poster.browse(image_type="logo")
            assert {r["image_type"] for r in logos["items"]} == {"logo"}
    finally:
        os.unlink(db_path)


def test_browse_title_wildcard_search():
    """A '*' in the browse query anchors a LIKE wildcard: '*1952' = ends-with,
    '1952*' = starts-with, '*1952*' = contains; no '*' = substring (legacy)."""
    import tempfile
    from backend.util.database import ChubDB
    from backend.util.normalization import normalize_titles

    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None

        def get_adapter(self, *a, **k):
            return self

    titles = [
        "Time Capsule 1952",
        "The 1952 Incident",
        "Blade Runner 2049",
        "2001 A Space Odyssey",
        "Plain Movie",
    ]
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with ChubDB(_Log(), db_path=db_path) as db:
            for i, t in enumerate(titles):
                db.poster.upsert(
                    {
                        "title": t,
                        "normalized_title": normalize_titles(t),
                        "year": None,
                        "tmdb_id": None,
                        "tvdb_id": None,
                        "imdb_id": None,
                        "season_number": None,
                        "folder": "Owner",
                        "file": f"/src/{i}.png",
                        "style": None,
                        "priority": 0,
                        "image_type": "poster",
                        "asset_type": "movie",
                    }
                )

            def found(q):
                return {r["title"] for r in db.poster.browse(query=q, limit=100)["items"]}

            assert found("*1952") == {"Time Capsule 1952"}  # ends with
            assert found("*1952*") == {"Time Capsule 1952", "The 1952 Incident"}  # any
            assert found("2001*") == {"2001 A Space Odyssey"}  # starts with
            assert found("2049") == {"Blade Runner 2049"}  # no '*' => substring
    finally:
        os.unlink(db_path)


def test_poster_cache_search_only_defaults_to_zero():
    """A row inserted without search_only back-fills to 0 (matchable), so the
    column addition doesn't change existing rows' matchability."""
    import sqlite3
    import tempfile
    from backend.util.database.schema import SchemaManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        SchemaManager.init_database(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(poster_cache)")}
        assert "search_only" in cols
        conn.execute("INSERT INTO poster_cache (title, file) VALUES ('Y', '/y/Y.png')")
        conn.commit()
        row = conn.execute(
            "SELECT search_only FROM poster_cache WHERE file='/y/Y.png'"
        ).fetchone()
        assert row[0] == 0
        conn.close()
    finally:
        os.unlink(db_path)


def test_search_only_rows_are_searchable_but_never_match():
    """search_only=1 rows (gdrive-only assets) appear in browse/owners but are
    excluded from every match-phase query, so they can't change applied
    posters."""
    import tempfile
    from backend.util.database import ChubDB

    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None

        def get_adapter(self, *a, **k):
            return self

    def _logo(title, norm, year, folder, file, search_only):
        return {
            "title": title,
            "normalized_title": norm,
            "year": year,
            "tmdb_id": None,
            "tvdb_id": None,
            "imdb_id": None,
            "season_number": None,
            "folder": folder,
            "file": file,
            "style": None,
            "priority": 0,
            "image_type": "logo",
            "asset_type": "movie",
            "search_only": search_only,
        }

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        with ChubDB(_Log(), db_path=db_path) as db:
            db.poster.upsert(
                _logo(
                    "Extras Movie",
                    "extrasmovie",
                    2023,
                    "Owned",
                    "/src/Owned/Extras Movie (2023) - Logo.png",
                    0,
                )
            )
            db.poster.upsert(
                _logo(
                    "Extras Only",
                    "extrasonly",
                    2024,
                    "Tarantula212",
                    "/gdrive/Extras/Tarantula212/Extras Only (2024) - Logo.png",
                    1,
                )
            )

            # Matching: the owned logo matches; the search-only one never does.
            assert (
                db.poster.get_by_normalized_title(
                    "extrasmovie", year=2023, image_type="logo"
                )
                is not None
            )
            assert (
                db.poster.get_by_normalized_title(
                    "extrasonly", year=2024, image_type="logo"
                )
                is None
            )
            cand_titles = {
                c["title"]
                for c in db.poster.get_candidates_by_prefix(
                    "Extras Only", image_type="logo"
                )
            }
            assert "Extras Only" not in cand_titles  # search-only excluded
            assert "Extras Movie" in cand_titles  # owned, shares the 'ext' prefix

            # Search surfaces: both rows appear; the search-only owner is listed.
            artwork = db.poster.browse(image_type="artwork")
            assert {"Extras Movie", "Extras Only"} <= {
                r["title"] for r in artwork["items"]
            }
            assert "Tarantula212" in db.poster.get_distinct_owners(image_type="artwork")
    finally:
        os.unlink(db_path)


def test_media_and_collection_have_mtime_columns():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        SchemaManager.init_database(conn)
        for table in ("media_cache", "collections_cache"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "file_mtime" in cols, f"{table} missing file_mtime"
        maa_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(media_asset_matches)")
        }
        assert "source_mtime" in maa_cols
        conn.close()
    finally:
        os.unlink(db_path)
