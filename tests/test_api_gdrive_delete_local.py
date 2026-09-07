"""Tests for POST /api/posters/gdrive/delete-local.

Safely removing a configured GDrive drive's local synced folder and purging
its cached poster rows. These exercise the real filesystem + a real on-disk
SQLite DB so the guardrails (config membership, allow-list, root refusal) and
the actual rmtree + row purge run for real."""

import os
import sys
import tempfile

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import posters as posters_router  # noqa: E402
from backend.util import config as config_mod  # noqa: E402
from backend.util.config import ChubConfig, GDriveListEntry  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    """Logger satisfying the get_adapter / log-method API without writing."""

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
    """Fresh FastAPI app with the posters router and a real on-disk DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(posters_router.router)

    yield app, db, path

    try:
        db.__exit__(None, None, None)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _seed_poster(db, file_path):
    db.poster.execute_query(
        "INSERT INTO poster_cache (file, title, year, asset_type, season_number, "
        "normalized_title) VALUES (?, ?, ?, 'movie', NULL, ?)",
        (file_path, "Movie", 2020, "movie"),
    )


def _count(db):
    return db.poster.execute_query(
        "SELECT COUNT(*) AS total FROM poster_cache", fetch_one=True
    )["total"]


def _patch_config(monkeypatch, gdrive_locations):
    """Point the endpoint's load_config() at a config whose gdrive_list has
    exactly the given locations."""
    cfg = ChubConfig()
    cfg.sync_gdrive.gdrive_list = [
        GDriveListEntry(id=f"id{i}", name=f"Drive{i}", location=loc)
        for i, loc in enumerate(gdrive_locations)
    ]
    monkeypatch.setattr(config_mod, "load_config", lambda: cfg)
    return cfg


def test_deletes_folder_and_purges_rows(db_app, monkeypatch, tmp_path):
    app, db, _ = db_app
    drive = tmp_path / "extras_drive"
    (drive / "sub").mkdir(parents=True)
    (drive / "sub" / "poster.jpg").write_text("x")
    loc = str(drive)

    _patch_config(monkeypatch, [loc])
    _seed_poster(db, os.path.join(loc, "sub", "poster.jpg"))
    _seed_poster(db, os.path.join(loc, "movie.jpg"))
    _seed_poster(db, "/some/other/place/keep.jpg")
    assert _count(db) == 3

    client = TestClient(app)
    resp = client.post("/api/posters/gdrive/delete-local", json={"location": loc})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["folder_removed"] is True
    assert data["deleted_rows"] == 2
    assert not os.path.exists(loc), "the drive folder should be gone from disk"
    # The unrelated row survives — only this drive's prefix is purged.
    assert _count(db) == 1


def test_rejects_unconfigured_path(db_app, monkeypatch, tmp_path):
    app, db, _ = db_app
    configured = tmp_path / "configured"
    configured.mkdir()
    stray = tmp_path / "stray"
    stray.mkdir()

    _patch_config(monkeypatch, [str(configured)])

    client = TestClient(app)
    resp = client.post(
        "/api/posters/gdrive/delete-local", json={"location": str(stray)}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "GDRIVE_LOCATION_NOT_CONFIGURED"
    # A path that isn't a configured drive is never touched.
    assert os.path.isdir(str(stray))


def test_refuses_filesystem_root(db_app, monkeypatch):
    app, db, _ = db_app
    # A pathological drive configured at "/". Membership + allow-list pass, but
    # the root guard must refuse — and must NOT delete anything.
    _patch_config(monkeypatch, ["/"])

    client = TestClient(app)
    resp = client.post("/api/posters/gdrive/delete-local", json={"location": "/"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "GDRIVE_LOCATION_UNSAFE"
    assert os.path.isdir("/")


def test_missing_folder_still_purges_rows(db_app, monkeypatch, tmp_path):
    app, db, _ = db_app
    # Folder already deleted (e.g. user rm'd it manually) but rows linger.
    gone = tmp_path / "already_deleted"
    loc = str(gone)  # never created on disk
    _patch_config(monkeypatch, [loc])
    _seed_poster(db, os.path.join(loc, "poster.jpg"))
    assert _count(db) == 1

    client = TestClient(app)
    resp = client.post("/api/posters/gdrive/delete-local", json={"location": loc})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["folder_removed"] is False
    assert data["deleted_rows"] == 1
    assert _count(db) == 0


def test_requires_location(db_app, monkeypatch):
    app, db, _ = db_app
    _patch_config(monkeypatch, [])
    client = TestClient(app)
    resp = client.post("/api/posters/gdrive/delete-local", json={})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "GDRIVE_LOCATION_REQUIRED"


def test_rejects_flag_like_location(db_app, monkeypatch):
    app, db, _ = db_app
    _patch_config(monkeypatch, [])
    client = TestClient(app)
    resp = client.post(
        "/api/posters/gdrive/delete-local", json={"location": "--delete-after"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "GDRIVE_LOCATION_REQUIRED"
