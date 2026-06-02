"""Tests for the Unmatched-page poster reset accessors:
- MediaCache.reset_match_state / CollectionCache.reset_match_state

Both preserve user-curated state (ignored / locked) while returning the rest to
all-missing.
"""

from types import SimpleNamespace

import pytest

from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _insert_media(db, table, id_, *, ignored=0, user_confirmed=0):
    cols = [
        "id", "asset_type", "title", "matched", "match_status",
        "match_confidence", "match_reason", "matched_poster_file",
        "matched_at", "ignored", "user_confirmed",
    ]
    vals = [
        id_, "movie", f"Title {id_}", 1, "matched", 0.9, "id match",
        "/p.png", "2026-06-02", ignored, user_confirmed,
    ]
    if table == "media_cache":  # identity_key is NOT NULL + UNIQUE on media_cache
        cols.append("identity_key")
        vals.append(f"key-{id_}")
    placeholders = ", ".join("?" for _ in cols)
    db.worker.execute_query(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )


def _row(db, table, id_):
    return db.worker.execute_query(
        f"SELECT * FROM {table} WHERE id=?", (id_,), fetch_one=True
    )


@pytest.mark.parametrize("table,accessor", [("media_cache", "media"), ("collections_cache", "collection")])
def test_reset_match_state_preserves_ignored_and_locked(db, table, accessor):
    _insert_media(db, table, 1)  # plain matched -> should reset
    _insert_media(db, table, 2, ignored=1)  # ignored -> preserved
    _insert_media(db, table, 3, user_confirmed=1)  # locked -> preserved

    reset = getattr(db, accessor).reset_match_state()
    assert reset == 1  # only the plain matched row counted

    plain = _row(db, table, 1)
    assert plain["matched"] == 0
    assert plain["match_status"] is None
    assert plain["match_confidence"] is None
    assert plain["match_reason"] is None
    assert plain["matched_poster_file"] is None
    assert plain["matched_at"] is None

    ignored = _row(db, table, 2)
    assert ignored["matched"] == 1 and ignored["ignored"] == 1
    locked = _row(db, table, 3)
    assert locked["matched"] == 1 and locked["user_confirmed"] == 1
