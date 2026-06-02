"""Tests for the System maintenance API endpoints (/api/system/db-stats,
/api/system/db/vacuum, /api/system/db/poster-cache/clear).

These spin up a real on-disk SQLite DB so VACUUM and row-count queries
exercise the actual SQL paths rather than mocked stand-ins."""

import os
import sys
import tempfile

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import system as system_router  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    """Logger that satisfies the get_adapter / log-method API used by the
    handlers + ChubDB without writing anywhere."""

    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db_app():
    """Build a fresh FastAPI app with a real on-disk SQLite DB attached."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    db.__enter__()
    # Force schema init so the system endpoints have tables to query
    db._ensure_schema_initialized()

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(system_router.router)

    yield app, db, path

    try:
        db.__exit__(None, None, None)
    finally:
        if os.path.exists(path):
            os.unlink(path)


# --- /api/system/db-stats ---


def test_db_stats_returns_expected_shape(db_app):
    app, _db, _path = db_app
    client = TestClient(app)

    resp = client.get("/api/system/db-stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True

    data = body["data"]
    # Top-level structure
    for key in (
        "tables",
        "page_size",
        "page_count",
        "freelist_count",
        "total_bytes",
        "free_bytes",
        "file_bytes",
        "schema_migrations",
    ):
        assert key in data, f"missing key {key}"

    # Sanity: page_size and page_count are positive ints
    assert data["page_size"] > 0
    assert data["page_count"] > 0
    assert data["total_bytes"] == data["page_size"] * data["page_count"]

    # `tables` is a list of {name, rows}
    assert isinstance(data["tables"], list)
    assert all("name" in t and "rows" in t for t in data["tables"])
    table_names = {t["name"] for t in data["tables"]}
    # core tables expected on a fresh schema
    for name in ("media_cache", "poster_cache", "schema_migrations"):
        assert name in table_names, f"missing table {name}"


# --- /api/system/db/vacuum ---


def test_vacuum_returns_byte_counts(db_app):
    app, _db, _path = db_app
    client = TestClient(app)

    resp = client.post("/api/system/db/vacuum")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]

    assert "bytes_before" in data
    assert "bytes_after" in data
    assert "bytes_reclaimed" in data
    assert "duration_ms" in data
    assert data["bytes_before"] >= data["bytes_after"]
    assert data["bytes_reclaimed"] == max(0, data["bytes_before"] - data["bytes_after"])
    assert data["duration_ms"] >= 0


def test_vacuum_reclaims_after_delete(db_app):
    """VACUUM should actually shrink the file after a sizeable DELETE."""
    app, db, path = db_app

    # Pump some data into poster_cache + delete it to create free pages
    for i in range(2000):
        db.poster.execute_query(
            "INSERT INTO poster_cache (file, title, year, asset_type, season_number, "
            "normalized_title, tmdb_id) VALUES (?, ?, ?, 'movie', NULL, ?, ?)",
            (f"/tmp/poster_{i}.jpg", f"Movie {i}", 2020, f"movie{i}", i),
        )
    db.poster.execute_query("DELETE FROM poster_cache")

    size_before = os.path.getsize(path)
    client = TestClient(app)
    resp = client.post("/api/system/db/vacuum")
    assert resp.status_code == 200
    size_after = os.path.getsize(path)
    assert size_after < size_before, "VACUUM should reclaim space after a big DELETE"


# --- /api/system/db/poster-cache/clear ---


def test_clear_poster_cache_empties_table(db_app):
    app, db, _path = db_app

    # Seed a couple of rows
    for i in range(3):
        db.poster.execute_query(
            "INSERT INTO poster_cache (file, title, year, asset_type, season_number, "
            "normalized_title) VALUES (?, ?, ?, 'movie', NULL, ?)",
            (f"/tmp/poster_{i}.jpg", f"Movie {i}", 2020, f"movie{i}"),
        )

    row = db.poster.execute_query(
        "SELECT COUNT(*) AS total FROM poster_cache", fetch_one=True
    )
    assert row["total"] == 3

    client = TestClient(app)
    resp = client.post("/api/system/db/poster-cache/clear")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["deleted"] == 3

    row = db.poster.execute_query(
        "SELECT COUNT(*) AS total FROM poster_cache", fetch_one=True
    )
    assert row["total"] == 0


# --- /api/system/db/poster-matches/reset ---


def test_reset_poster_matches_preserves_ignored_and_locked(db_app):
    app, db, _path = db_app

    def seed(table, id_, ignored=0, locked=0):
        cols = ["id", "asset_type", "title", "matched", "match_status",
                "ignored", "user_confirmed"]
        vals = [id_, "movie", f"T{id_}", 1, "matched", ignored, locked]
        if table == "media_cache":  # identity_key NOT NULL + UNIQUE
            cols.append("identity_key")
            vals.append(f"key-{id_}")
        ph = ", ".join("?" for _ in cols)
        db.worker.execute_query(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})", tuple(vals)
        )

    seed("media_cache", 1)
    seed("media_cache", 2, ignored=1)
    seed("media_cache", 3, locked=1)
    seed("collections_cache", 1)

    client = TestClient(app)
    resp = client.post("/api/system/db/poster-matches/reset")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["reset"] == 2  # 1 media + 1 collection
    assert body["data"]["media"] == 1
    assert body["data"]["collections"] == 1

    # Plain row reset; curated rows preserved.
    assert db.worker.execute_query(
        "SELECT matched FROM media_cache WHERE id=1", fetch_one=True
    )["matched"] == 0
    assert db.worker.execute_query(
        "SELECT matched FROM media_cache WHERE id=2", fetch_one=True
    )["matched"] == 1
    assert db.worker.execute_query(
        "SELECT matched FROM media_cache WHERE id=3", fetch_one=True
    )["matched"] == 1


# --- /api/system/db/artwork-matches/reset ---


def test_reset_artwork_matches_keeps_ignored(db_app):
    app, db, _path = db_app

    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=1,
        image_type="logo",
        source="fanart",
        matched_url="http://x/l.png",
        applied_method="plex",
        match_status="applied",
    )
    db.media_asset_matches.set_ignored("media", 2, "background", True)

    client = TestClient(app)
    resp = client.post("/api/system/db/artwork-matches/reset")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["deleted"] == 1  # only the applied row

    assert db.media_asset_matches.get_one("media", 1, "logo") is None
    assert db.media_asset_matches.get_one("media", 2, "background")["ignored"] == 1
