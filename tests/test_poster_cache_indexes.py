"""Guards for the poster_cache index set.

image_type and search_only are ~single-valued on a real library, so indexing
them can never narrow a scan — and without ANALYZE stats the planner picked
them over the selective indexes on the hot match queries."""

import sqlite3

from backend.util.database.schema import SchemaManager

UNSELECTIVE = (
    "poster_cache_image_type_idx",
    "poster_cache_search_only_idx",
    "poster_cache_created_at_idx",
)


def _indexes(conn) -> set:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='poster_cache'"
        )
    }


def test_fresh_schema_omits_the_unselective_indexes(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "chub.db"))
    SchemaManager.init_database(conn)

    names = _indexes(conn)
    for idx in UNSELECTIVE:
        assert idx not in names, f"{idx} should not be created on a fresh DB"
    # The selective ones must survive.
    assert "poster_cache_normalized_title_idx" in names
    assert "poster_cache_tmdb_id_idx" in names
    assert "poster_cache_imdb_id_idx" in names
    conn.close()


def test_migration_drops_them_from_an_existing_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "chub.db"))
    SchemaManager.init_database(conn)

    # Re-create them as a DB upgraded from an older CHUB would have them, and
    # clear the migration ledger so the drop is eligible to run.
    for idx, col in zip(UNSELECTIVE, ("image_type", "search_only", "created_at")):
        conn.execute(f"CREATE INDEX {idx} ON poster_cache ({col})")
    conn.execute("DELETE FROM schema_migrations")
    conn.commit()
    assert UNSELECTIVE[0] in _indexes(conn)

    SchemaManager.init_database(conn)

    names = _indexes(conn)
    for idx in UNSELECTIVE:
        assert idx not in names, f"migration did not drop {idx}"
    conn.close()


def test_unique_constraint_index_is_untouched(tmp_path):
    """sqlite_autoindex backs UNIQUE(...) — it is the upsert conflict target."""
    conn = sqlite3.connect(str(tmp_path / "chub.db"))
    SchemaManager.init_database(conn)

    assert any(n.startswith("sqlite_autoindex_poster_cache") for n in _indexes(conn))
    conn.close()
