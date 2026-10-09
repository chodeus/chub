"""A variant is deleted only if Plex's live DB, read at delete time, no longer uses it."""

import sqlite3
from types import SimpleNamespace

import pytest

from backend.util.plex_metadata import (
    IN_USE_IMAGE_COLUMNS,
    PLEX_DB_NAME,
    TAG_IN_USE_IMAGE_COLUMNS,
    delete_variant,
    get_in_use_hashes,
    variant_in_use,
)

VALUES = [
    "upload://posters/aaa111",
    "metadata://posters/com.plexapp.agents.themoviedb_bbb222",
    "upload://posters/ccc333?t=1700000000",
    "http://example.invalid/ddd444",
    "upload://art/a_c",
]
CANDIDATES = [
    "aaa111",
    "com.plexapp.agents.themoviedb_bbb222",
    "ccc333",
    "ddd444",
    "a_c",
    "aXc",
    "tag555",
    "nope",
]


def _plex(tmp_path, columns=IN_USE_IMAGE_COLUMNS, with_tags=True):
    """A Plex-shaped library DB under tmp_path; returns (plex_path, db_path)."""
    db_dir = tmp_path / "Plug-in Support" / "Databases"
    db_dir.mkdir(parents=True)
    db = db_dir / PLEX_DB_NAME
    con = sqlite3.connect(db)
    con.execute(
        f"CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, "
        f"{', '.join(c + ' TEXT' for c in columns)})"
    )
    for value in VALUES:
        con.execute("INSERT INTO metadata_items (user_thumb_url) VALUES (?)", (value,))
    if with_tags:
        con.execute(
            f"CREATE TABLE tags (id INTEGER PRIMARY KEY, "
            f"{', '.join(c + ' TEXT' for c in TAG_IN_USE_IMAGE_COLUMNS)})"
        )
        con.execute("INSERT INTO tags (user_art_url) VALUES ('upload://posters/tag555')")
    con.commit()
    con.close()
    return str(tmp_path), str(db)


@pytest.mark.parametrize(
    "columns, with_tags",
    [(IN_USE_IMAGE_COLUMNS, True), (("user_thumb_url",), False)],
    ids=["full schema", "older schema without tags or newer columns"],
)
def test_agrees_with_the_scan_on_every_value(tmp_path, columns, with_tags):
    plex_path, db = _plex(tmp_path, columns=columns, with_tags=with_tags)
    scanned = get_in_use_hashes(db)

    live = {name: variant_in_use(plex_path, name) for name in CANDIDATES}

    assert live == {name: name in scanned for name in CANDIDATES}
    assert live["aaa111"] is True


def test_none_when_the_db_is_missing_or_unreadable(tmp_path):
    missing = variant_in_use(str(tmp_path), "aaa111")
    db_dir = tmp_path / "Plug-in Support" / "Databases"
    db_dir.mkdir(parents=True)
    (db_dir / PLEX_DB_NAME).write_bytes(b"not a database")
    unreadable = variant_in_use(str(tmp_path), "aaa111")

    assert (missing, unreadable) == (None, None)


def _variant(tmp_path, name):
    path = tmp_path / "Metadata" / "Movies" / "a" / "x.bundle" / "Uploads" / "posters" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_delete_keeps_a_variant_plex_uses_now_and_removes_one_it_does_not(tmp_path):
    plex_path, _ = _plex(tmp_path)
    used = _variant(tmp_path, "aaa111")
    unused = _variant(tmp_path, "zzz999")

    kept = delete_variant(str(used), plex_path=plex_path)
    removed = delete_variant(str(unused), plex_path=plex_path)

    assert (kept, removed) == ("in_use", "deleted")
    assert used.exists()
    assert not unused.exists()


def test_delete_keeps_the_file_when_plex_cannot_be_checked(tmp_path):
    unused = _variant(tmp_path, "zzz999")

    outcome = delete_variant(str(unused), plex_path=str(tmp_path))

    assert outcome == "unverified"
    assert unused.exists()


def _client(monkeypatch, outcome, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.api.posters as posters
    from backend.api.posters._shared import get_cleanarr_logger

    logger = SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
    )
    monkeypatch.setattr(
        "backend.util.plex_metadata.delete_variant", lambda path, plex_path: outcome
    )
    monkeypatch.setattr(
        "backend.api.posters.plex_metadata.get_plex_path", lambda: str(tmp_path)
    )
    app = FastAPI()
    app.include_router(posters.router)
    app.dependency_overrides[get_cleanarr_logger] = lambda: logger
    return TestClient(app)


@pytest.mark.parametrize(
    "outcome, status, code",
    [
        ("in_use", 409, "VARIANT_IN_USE"),
        ("unverified", 503, "VARIANT_CHECK_FAILED"),
        ("refused", 400, "VARIANT_DELETE_FAILED"),
        ("deleted", 200, None),
    ],
)
def test_route_answers_each_outcome(monkeypatch, tmp_path, outcome, status, code):
    client = _client(monkeypatch, outcome, tmp_path)

    res = client.request(
        "DELETE", "/api/posters/plex-metadata/variant", json={"path": "/x"}
    )

    assert res.status_code == status
    if code:
        assert code in res.text
